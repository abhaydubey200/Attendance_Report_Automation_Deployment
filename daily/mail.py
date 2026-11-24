"""Daily emails: plan one email per recipient, preview, approve, send (duplicate guard, retry, audit).

Plan (after each upload of a day):
  * every team lead / HOD gets ONE email: their team's detail and/or their department summary;
  * the Director gets the company summary by HOD (+ detail of the Director Office staff);
  * HR gets an exception email only when something cannot be routed.
Each email: counts first, then only the employees needing attention; the full roster of that recipient
only is attached (.xlsx, exceptions first) plus an interactive HTML dashboard of the same people.
"""

from __future__ import annotations

import io
import json
import time
from collections import Counter, defaultdict
from datetime import date, timedelta
from pathlib import Path

import xlsxwriter
from jinja2 import Environment, FileSystemLoader, select_autoescape
from sqlalchemy import select
from sqlalchemy.orm import Session

from core.config import Settings
from core.timeutils import now_utc
from daily import analysis, employees, routing
from daily.branding import excel_banner
from daily.mailer import Attachment, MailError, build_message, send
from daily.settings_store import get_email_settings, get_rules
from database.models.daily import DayUpload, EmailLog, EmployeeDay, MailItem
from security.audit import record_activity

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
PENDING, SENT, SAVED, FAILED, HELD, DISABLED, DUPLICATE, SUPERSEDED = (
    "PENDING", "SENT", "SAVED", "FAILED", "HELD", "DISABLED", "DUPLICATE", "SUPERSEDED")
TEST_SENT = "TEST_SENT"          # delivered only to the testing address; the real recipient has NOT received it
DELIVERED = (SENT, SAVED)
SENDABLE = (PENDING, FAILED, TEST_SENT)
NO_RECORD = "NO_RECORD"
NOT_IN_MASTER = "NOT_IN_EMPLOYEE_MASTER"
LABELS = {**analysis.STATUS_LABEL, NO_RECORD: "No attendance record"}
_env = Environment(loader=FileSystemLoader(Path(__file__).parent / "templates"), autoescape=select_autoescape(["html"]))
_env.filters["t12"] = analysis.t12
SLEEP = time.sleep          # patched in tests


def delivered_statuses(cfg) -> tuple[str, ...]:
    """Statuses that mean "this recipient already has the day's email". In live mode only a real send counts:
    an email SAVED to the outbox in test mode was never delivered, so it must not block the live one."""
    return (SENT,) if cfg.mode == "live" else DELIVERED


def sendable_statuses(cfg) -> tuple[str, ...]:
    """Statuses that can still be approved / sent. In live mode that includes emails only saved in test mode."""
    return SENDABLE + ((SAVED,) if cfg.mode == "live" else ())


# ---------------------------------------------------------------------------- rows + counts
def _rows(session: Session, upload_id: int) -> dict[str, dict]:
    out = {}
    for e in session.scalars(select(EmployeeDay).where(EmployeeDay.upload_id == upload_id)):
        out[e.employee_code.upper()] = {
            "code": e.employee_code, "name": e.employee_name or "", "department": e.department or "", "hod": e.hod_name or "",
            "team": e.team or "", "manager": e.reporting_manager or "", "category": e.category, "status": e.status,
            "status_label": LABELS.get(e.status, e.status), "in_time": e.in_time, "out_time": e.out_time,
            "work_hours": round(e.work_minutes / 60, 2) if e.work_minutes is not None else None,
            "late_minutes": e.late_minutes, "early_minutes": e.early_minutes, "leave_type": e.leave_type,
            "source": e.source or "HRMS", "permission": e.permission or "", "on_duty": e.on_duty or "",
            "flags": (e.flags or "").split(",") if e.flags else []}
    return out


def _row_for(r: routing.Route, rows: dict[str, dict]) -> dict:
    row = rows.get(r.code.upper())
    if row is None:
        row = {"code": r.code, "name": r.name, "category": "", "status": NO_RECORD, "status_label": LABELS[NO_RECORD], "in_time": None,
               "out_time": None, "work_hours": None, "late_minutes": 0, "early_minutes": 0, "leave_type": None, "source": "",
               "permission": "", "on_duty": "", "flags": []}
    return {**row, "name": r.name or row["name"], "department": r.department, "hod": r.hod, "team": r.team, "manager": r.manager}


def attention(row: dict) -> str | None:
    """Why this employee needs a look today (None = fine, covered by the counts)."""
    reason = _attention(row)
    if reason and "PERMISSION_PENDING" in row.get("flags", []):
        pending = [p for p in (row.get("permission") or "").split("; ") if p.startswith("Pending")]
        reason += f" (permission pending{pending[0][len('Pending'):]})" if pending else " (permission pending)"
    if reason and "ON_DUTY_PENDING" in row.get("flags", []):
        reason += f" ({onduty_pending_text(row)})"
    return reason


def onduty_pending_text(row: dict) -> str:
    """e.g. "work from home request pending, full day" - from the stored on-duty note."""
    pend = [p for p in (row.get("on_duty") or "").split("; ") if " pending" in p]
    if not pend:
        return "on-duty request pending"
    what, _, when = pend[0].partition(" pending")
    when = when.strip(" ()")
    return f"{what.lower()} request pending" + (f", {when}" if when else "")


def _attention(row: dict) -> str | None:
    if row["status"] == "ABSENT":
        return "Absent"
    if row["status"] == "MISSING_PUNCH":
        which = (" - no in-punch" if row.get("out_time") and not row.get("in_time")
                 else " - no out-punch" if row.get("in_time") and not row.get("out_time") else "")
        return f"Missing punch{which}" + (f", late by {analysis.mins_hm(row['late_minutes'])} hrs" if "LATE" in row["flags"] else "")
    reasons = []
    if "LATE" in row["flags"]:
        reasons.append(f"Late by {analysis.mins_hm(row['late_minutes']) or '0:00'} hrs")
    if "LEFT_EARLY" in row["flags"]:
        short = analysis.mins_hm(row["early_minutes"]) or "0:00"
        reasons.append(f"left early ({short} hrs short of required hours)" if reasons
                       else f"Left early ({short} hrs short of required hours)")
    return ", ".join(reasons) or None


def counts(rows: list[dict], single_punch_counts: bool = True) -> dict:
    c = Counter(r["status"] for r in rows)
    tracked = len(rows) - c["NOT_TRACKED"] - c["WEEK_OFF"] - c["HOLIDAY"] - c[NO_RECORD]
    present_eq = c["PRESENT"] + c["ON_DUTY"] + c["WFH"] + (c["MISSING_PUNCH"] if single_punch_counts else 0) + 0.5 * c["HALF_DAY"]
    return {"total": len(rows), "present": c["PRESENT"], "absent": c["ABSENT"], "leave": c["LEAVE"] + c["HALF_DAY"],
            "od": c["ON_DUTY"], "wfh": c["WFH"], "late": sum(1 for r in rows if "LATE" in r["flags"]),
            "left_early": sum(1 for r in rows if "LEFT_EARLY" in r["flags"]),
            "missing_punch": c["MISSING_PUNCH"], "week_off": c["WEEK_OFF"], "holiday": c["HOLIDAY"], "not_tracked": c["NOT_TRACKED"], "no_record": c[NO_RECORD],
            "attendance_pct": round(100 * present_eq / tracked, 1) if tracked else None,
            "attention": sum(1 for r in rows if attention(r)),
            # the same people split so that each is counted once (for the headline)
            "present_late": sum(1 for r in rows if r["status"] == "PRESENT" and "LATE" in r["flags"]),
            "present_early": sum(1 for r in rows if r["status"] == "PRESENT" and "LEFT_EARLY" in r["flags"]),
            "att_late": sum(1 for r in rows if "LATE" in r["flags"] and r["status"] not in ("ABSENT", "MISSING_PUNCH")),
            "att_late_early": sum(1 for r in rows if "LATE" in r["flags"] and "LEFT_EARLY" in r["flags"]
                                  and r["status"] not in ("ABSENT", "MISSING_PUNCH")),
            "att_early": sum(1 for r in rows if "LEFT_EARLY" in r["flags"] and "LATE" not in r["flags"]
                             and r["status"] not in ("ABSENT", "MISSING_PUNCH"))}


HISTORY_DAYS = 5          # uploaded days looked at for patterns (absent in a row, repeatedly late, ...)
HISTORY_WINDOW = 7        # ... and only those within this many calendar days of the report date


def headline(c: dict | None, who: str, day: str = "") -> str | None:
    """One sentence a busy manager can act on (always names the date, never "today")."""
    if not c or not c["total"]:
        return None
    on = f" on {day}" if day else ""
    if not c["attention"]:
        return f"All {c['total']} people in {who} are accounted for{on} - nobody needs attention."
    late, both = c.get("att_late", c["late"]), c.get("att_late_early", 0)
    if not both:
        also = ""
    elif both == late:
        also = " (also left early)" if late == 1 else " (both also left early)" if late == 2 else " (all also left early)"
    else:
        also = f" ({both} also left early)"
    parts = [f"{c['absent']} absent" if c["absent"] else "", f"{c['missing_punch']} missing punch" if c["missing_punch"] else "",
             f"{late} late{also}" if late else "", f"{c.get('att_early', 0)} left early" if c.get("att_early") else ""]
    verb = "needs" if c["attention"] == 1 else "need"
    return f"{c['attention']} of {c['total']} people in {who} {verb} attention{on}: " + ", ".join(x for x in parts if x) + "."


def subject_numbers(c: dict) -> str:
    """'2 absent · 3 late' for the subject line (the most useful counts only)."""
    if c.get("hr"):
        h = c["hr"]
        parts = [f"{h['records']} record(s) to fix" if h.get("records") else "",
                 f"{h['missing_punch']} missing punch" if h.get("missing_punch") else "",
                 f"{h['permissions']} permission(s) pending" if h.get("permissions") else "",
                 f"{h['onduty']} on-duty request(s) pending" if h.get("onduty") else ""]
        return " · ".join(x for x in parts if x) or "nothing to fix"
    if c.get("exceptions"):
        return f"{c['exceptions']} record(s) to fix"
    main = c.get("company") or (c["team"] if c["team"]["total"] else (c.get("summary") or c["team"]))
    if main.get("total") and main.get("attendance_pct") is None:
        return "week off / holiday"
    parts = [f"{main[k]} {label}" for k, label in (("absent", "absent"), ("late", "late"), ("missing_punch", "missing punch")) if main.get(k)]
    return " · ".join(parts) if parts else ("all present" if main.get("total") else "no attendance")


def _previous_upload(session: Session, day: date) -> DayUpload | None:
    return session.scalar(select(DayUpload).where(DayUpload.report_date < day, DayUpload.is_current.is_(True))
                          .order_by(DayUpload.report_date.desc()))


def change(now: dict | None, before: dict | None) -> dict:
    """Differences with the previous uploaded day (None when there is nothing to compare)."""
    out = {"absent": None, "late": None, "missing_punch": None, "attendance_pct": None}
    if not now or not before or not before.get("total"):
        return out
    for k in ("absent", "late", "missing_punch"):
        out[k] = now[k] - before[k]
    if now.get("attendance_pct") is not None and before.get("attendance_pct") is not None:
        out["attendance_pct"] = round(now["attendance_pct"] - before["attendance_pct"], 1)
    return out


def _history(session: Session, day: date, codes: set[str]) -> dict[str, list[dict]]:
    """code -> statuses of the last HISTORY_DAYS uploaded days up to `day` (newest first)."""
    ups = list(session.execute(select(DayUpload.upload_id, DayUpload.report_date).where(
        DayUpload.report_date <= day, DayUpload.report_date > day - timedelta(days=HISTORY_WINDOW),
        DayUpload.is_current.is_(True)).order_by(DayUpload.report_date.desc()).limit(HISTORY_DAYS)))
    if not ups or not codes:
        return {}
    when = {u: d for u, d in ups}
    out: dict[str, list[dict]] = defaultdict(list)
    q = select(EmployeeDay.upload_id, EmployeeDay.employee_code, EmployeeDay.status, EmployeeDay.flags).where(
        EmployeeDay.upload_id.in_(list(when)))
    for upload_id, code, status, flags in session.execute(q):
        if code.upper() in codes:
            out[code.upper()].append({"date": when[upload_id], "status": status, "flags": (flags or "").split(",")})
    for v in out.values():
        v.sort(key=lambda x: x["date"], reverse=True)
    return out


def pattern(days: list[dict]) -> str | None:
    """'absent 3 days in a row', 'late 4 of the last 5 days' ... (needs at least 2 days of history)."""
    if len(days) < 2:
        return None
    notes = []
    streak = 0
    for d in days:
        if d["status"] != "ABSENT":
            break
        streak += 1
    if streak >= 2:
        notes.append(f"absent on the last {streak} report days")
    late = sum(1 for d in days if "LATE" in d["flags"])
    if late >= 3:
        notes.append(f"late on {late} of the last {len(days)} report days")
    mp = sum(1 for d in days if d["status"] == "MISSING_PUNCH")
    if mp >= 2:
        notes.append(f"missing punch on {mp} of the last {len(days)} report days")
    return "; ".join(notes) or None


TREND_DAYS = 7            # uploaded days shown in the mini trend of every email (and the "Last 7 days" sheet)
STREAK_ALERT = 3          # absent this many report days in a row -> Director concern / HR action
NO_HOD = "No HOD assigned"
ISSUE_TEXT = {            # routing issue codes -> plain words for HR
    "HOD_EMAIL_CONFLICT": "Two different email addresses for the same HOD",
    "NO_HOD_EMAIL": "No HOD email address",
    "INVALID_SUB_SPLIT_EMAIL": "Team lead email address is not valid",
    "MULTIPLE_SUB_SPLIT_EMAILS": "More than one team lead email address",
    "HOLD": "Held by HR",
}


def issue_text(issue: str | None) -> str:
    up = (issue or "").upper()
    return next((t for k, t in ISSUE_TEXT.items() if k in up), issue or "Could not be routed")


def recent_uploads(session: Session, day: date, n: int = TREND_DAYS) -> list[tuple[int, date]]:
    """(upload_id, date) of the last n uploaded days up to `day`, oldest first."""
    ups = session.execute(select(DayUpload.upload_id, DayUpload.report_date).where(
        DayUpload.report_date <= day, DayUpload.is_current.is_(True)).order_by(DayUpload.report_date.desc()).limit(n))
    return [(u, d) for u, d in ups][::-1]


def day_grid(session: Session, ups: list[tuple[int, date]], codes: set[str]) -> dict[str, dict[date, dict]]:
    """code -> {date -> minimal row (status, flags, times)} for the given uploads."""
    when = dict(ups)
    out: dict[str, dict[date, dict]] = defaultdict(dict)
    if not when or not codes:
        return out
    q = select(EmployeeDay.upload_id, EmployeeDay.employee_code, EmployeeDay.status, EmployeeDay.flags, EmployeeDay.in_time,
               EmployeeDay.out_time, EmployeeDay.late_minutes, EmployeeDay.early_minutes).where(EmployeeDay.upload_id.in_(list(when)))
    for u, code, st, fl, i, o, lm, em in session.execute(q):
        c = code.upper()
        if c in codes:
            out[c][when[u]] = {"status": st, "flags": fl.split(",") if fl else [], "in_time": i, "out_time": o,
                               "late_minutes": lm or 0, "early_minutes": em or 0, "permission": ""}
    return out


def trend(ups: list[tuple[int, date]], grid: dict[str, dict[date, dict]], codes: list[str]) -> list[dict]:
    """Attendance % per uploaded day for these people. A day where under 20% of them were due (Sunday, holiday) has pct None."""
    out = []
    for _, d in ups:
        rows = [grid[c][d] for c in codes if d in grid.get(c, {})]
        c = counts(rows) if rows else None
        due = (c["total"] - c["week_off"] - c["holiday"] - c["not_tracked"] - c["no_record"]) if c else 0
        working = bool(c) and c["attendance_pct"] is not None and due >= 0.2 * c["total"]
        out.append({"date": d, "label": f"{d:%a}", "day": f"{d:%d}", "pct": c["attendance_pct"] if working else None,
                    "absent": c["absent"] if c else 0, "late": c["late"] if c else 0})
    return out


def week_note(days: list[dict]) -> str | None:
    """Repeated trouble over the recent report days, even when the latest day was fine (newest first)."""
    if len(days) < 3:
        return None
    n = len(days)
    a = sum(1 for d in days if d["status"] == "ABSENT")
    lt = sum(1 for d in days if "LATE" in d["flags"])
    mp = sum(1 for d in days if d["status"] == "MISSING_PUNCH")
    notes = [f"absent {a} of the last {n} report days" if a >= 2 else "", f"late {lt} of the last {n} report days" if lt >= 3 else "",
             f"missing punch {mp} of the last {n} report days" if mp >= 2 else ""]
    return "; ".join(x for x in notes if x) or None


def absent_streak(days: list[dict]) -> int:
    n = 0
    for d in days:                       # newest first
        if d["status"] != "ABSENT":
            break
        n += 1
    return n


def team_table(rows: list[dict], before_of) -> list[dict]:
    """One line per HOD's team (Director / HR only): weakest attendance first."""
    groups: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        groups[r.get("hod") or NO_HOD].append(r)
    out = []
    for name, rs in groups.items():
        c = counts(rs)
        b = before_of(rs)
        out.append({"name": name, "people": c["total"], "pct": c["attendance_pct"], "absent": c["absent"], "late": c["late"],
                    "missing_punch": c["missing_punch"], "leave": c["leave"], "attention": c["attention"],
                    "change": change(c, b)["attendance_pct"]})
    out.sort(key=lambda t: (t["pct"] is None, t["pct"] if t["pct"] is not None else 0, -t["people"]))
    return out


def _sort_attention_first(rows: list[dict]) -> list[dict]:
    return sorted(rows, key=lambda r: (attention(r) is None, r.get("department") or "", r["name"]))


# ---------------------------------------------------------------------------- planning
def build_plan(session: Session, settings: Settings, upload: DayUpload, actor: str) -> list[MailItem]:
    """Create today's mail items for this upload. Earlier unsent items of the same day are superseded;
    recipients already sent for the day are marked DUPLICATE (sent once per recipient per day)."""
    cfg = get_email_settings(session, settings)
    day = upload.report_date
    undelivered = (HELD, DUPLICATE, DISABLED) + sendable_statuses(cfg)   # earlier rows of this day that were not delivered
    for old in session.scalars(select(MailItem).where(MailItem.report_date == day, ~MailItem.recipient_key.like("MONTHLY:%"),
                                                     MailItem.status.in_(undelivered))):
        old.status, old.note = SUPERSEDED, "Replaced by a newer upload of this day."
    delivered = {k for (k,) in session.execute(select(MailItem.recipient_key).where(MailItem.report_date == day,
                                                                                   MailItem.status.in_(delivered_statuses(cfg))))}
    rows = _rows(session, upload.upload_id)
    rs = routing.routes(session, day)
    in_master = {r.code.upper() for r in rs}
    master_codes = {e.code for e in employees.list_all(session)}
    unmatched = [code for code in rows if code not in master_codes]
    recs = routing.recipients(session, cfg, day, rs)
    items = []
    for rec in recs:
        content: dict = {"team": [r.code for r in rec.team], "summary": [r.code for r in rec.summary], "company": rec.company}
        hr_parts: dict = {}
        if rec.key == routing.HR:
            content["exceptions"] = ([{"code": r.code, "issue": r.issue or "Held"} for r in rec.team]
                                     + [{"code": code, "issue": NOT_IN_MASTER} for code in sorted(unmatched)])
            content["company"] = True        # HR action list covers the whole company (missing punches, permissions, ...)
            everyone = [_row_for(r, rows) for r in rs]
            hr_parts = {"records": len(content["exceptions"]),
                        "missing_punch": sum(1 for r in everyone if r["status"] == "MISSING_PUNCH"),
                        "permissions": sum(1 for r in everyone if "PERMISSION_PENDING" in r["flags"]),
                        "onduty": sum(1 for r in everyone if "ON_DUTY_PENDING" in r["flags"])}
            if not any(hr_parts.values()):
                continue                     # HR mail only on days with something to act on
        team_rows = [_row_for(r, rows) for r in rec.team]
        summary_rows = [_row_for(r, rows) for r in rec.summary]
        company_rows = [_row_for(r, rows) for r in rs] if content["company"] else []
        c = {"team": counts(team_rows), "summary": counts(summary_rows) if summary_rows else None,
             "company": counts(company_rows) if company_rows else None,
             "exceptions": len(content.get("exceptions", [])), "hr": hr_parts or None}
        status, note = (PENDING, None) if rec.status == "OK" else (rec.status, rec.note)
        main = c["company"] or (c["team"] if c["team"]["total"] else (c["summary"] or c["team"]))
        if status == PENDING and rec.key != routing.HR and main["total"] and main["attendance_pct"] is None:
            status, note = DISABLED, "Not sent: nobody was due to work on this day (week off / holiday)."
        if status == HELD and cfg.test_recipient:
            status, note = PENDING, f"Testing: {rec.note} Goes to the test address only."
        if status == PENDING and rec.key in delivered:
            status, note = DUPLICATE, "Already sent for this day (sent once per recipient per day)."
        name = rec.name
        item = MailItem(upload_id=upload.upload_id, report_date=day, recipient_key=rec.key, recipient_name=name, role=rec.role,
                        to_addrs=", ".join(rec.to) or None, cc_addrs=", ".join(rec.cc) or None,
                        subject=f"{cfg.subject_prefix} | {day:%d-%b-%Y} | {name} | {subject_numbers(c)}", content=json.dumps(content),
                        counts=json.dumps(c), status=status, note=note, attempts=0)
        session.add(item)
        items.append(item)
    session.flush()
    record_activity(session, "MAIL_PLAN", "SUCCESS", username=actor,
                    detail={"date": day.isoformat(), "emails": len(items), "status": dict(Counter(i.status for i in items)),
                            "not_in_master": len(unmatched), "in_master": len(in_master)})
    return items


def items_for(session: Session, day: date, include_old: bool = False) -> list[MailItem]:
    stmt = select(MailItem).where(MailItem.report_date == day, ~MailItem.recipient_key.like("MONTHLY:%"))
    if not include_old:
        stmt = stmt.where(MailItem.status != SUPERSEDED)
    return list(session.scalars(stmt.order_by(MailItem.id)))


def item_dict(i: MailItem, sendable: tuple[str, ...] = SENDABLE) -> dict:
    """`sendable`: the statuses that can still be approved (``sendable_statuses(cfg)``)."""
    c = json.loads(i.counts)
    return {"id": i.id, "sendable": i.status in sendable, "report_date": i.report_date.isoformat(), "key": i.recipient_key, "name": i.recipient_name, "role": i.role,
            "to": i.to_addrs or "", "cc": i.cc_addrs or "", "subject": i.subject, "status": i.status, "note": i.note,
            "attempts": i.attempts, "team": c["team"]["total"], "summary": (c.get("summary") or {}).get("total", 0),
            "company": (c.get("company") or {}).get("total", 0), "exceptions": c.get("exceptions", 0),
            "attention": ((c.get("company") or {}).get("attention", 0) if c.get("company")
                          else c["team"]["attention"] if c["team"]["total"] else (c.get("summary") or {}).get("attention", 0)),
            "counts": c, "sent_at": i.sent_at.isoformat() if i.sent_at else None, "approved_by": i.approved_by}


# ---------------------------------------------------------------------------- content
def _sections(session: Session, item: MailItem) -> dict:
    content = json.loads(item.content)
    rows = _rows(session, item.upload_id)
    rs = {r.code: r for r in routing.routes(session, item.report_date)}

    def pick(codes: list[str]) -> list[dict]:
        out = []
        for code in codes:
            r = rs.get(code)
            if r is not None:
                out.append(_row_for(r, rows))
            elif code.upper() in rows:
                out.append(rows[code.upper()])
        return out

    team = pick(content["team"])
    summary = pick(content["summary"])
    company = pick(list(rs)) if content.get("company") or item.recipient_key == routing.HR else []
    exceptions = []
    for x in content.get("exceptions", []):
        row = rows.get(x["code"].upper())
        r = rs.get(x["code"])
        exceptions.append({"code": x["code"], "issue": x["issue"], "name": (r.name if r else (row or {}).get("name", "")),
                           "department": (r.department if r else ""), "hod": (r.hod if r else ""),
                           "status_label": (row or {}).get("status_label", LABELS[NO_RECORD]),
                           "source": (row or {}).get("source", ""), "category": (row or {}).get("category", "")})
    return {"team": team, "summary": summary, "company": company, "exceptions": exceptions}


def render(session: Session, settings: Settings, item: MailItem) -> tuple[str, str, list[Attachment]]:
    """(html, text, attachments) for one mail item."""
    if json.loads(item.content).get("kind") == "monthly":
        from daily import monthly

        return monthly.render(session, settings, item)
    cfg = get_email_settings(session, settings)
    s = _sections(session, item)
    day = item.report_date.strftime(settings.app.date_format)
    prev_up = _previous_upload(session, item.report_date)
    prev_rows = _rows(session, prev_up.upload_id) if prev_up else {}

    def before(rows: list[dict]) -> dict | None:
        if not prev_up:
            return None
        return counts([dict(r, **{k: prev_rows[r["code"].upper()][k] for k in ("status", "flags")}) for r in rows
                       if r["code"].upper() in prev_rows])

    hist = _history(session, item.report_date, {r["code"].upper() for r in s["team"] + s["summary"] + s["company"]})
    kind = "hr" if item.recipient_key == routing.HR else "director" if s["company"] else "hod"

    def with_pattern(r: dict) -> dict:
        from daily.render import action_for

        pat = pattern(hist.get(r["code"].upper(), []))
        return dict(r, reason=attention(r), pattern=pat, action=action_for(r, pat))

    team_att = [with_pattern(r) for r in _sort_attention_first(s["team"]) if attention(r)]
    team_codes = {r["code"] for r in s["team"]}
    # department: only the recurring patterns of people outside the HOD's own team (the counts cover the rest)
    dept_patterns = [p for p in (with_pattern(r) for r in s["summary"] if r["code"] not in team_codes) if p["pattern"]]
    team_c = counts(s["team"]) if s["team"] else None
    summary_c = counts(s["summary"]) if s["summary"] else None
    company_c = counts(s["company"]) if s["company"] else None
    people = s["team"] + [r for r in s["summary"] if r["code"] not in team_codes]
    main_rows = s["company"] if kind != "hod" else (s["team"] or s["summary"])

    # last 7 uploaded days: mini trend + "watch this week" + absence streaks + the Excel "Last 7 days" sheet
    ups = recent_uploads(session, item.report_date)
    grid_rows = s["company"] if kind != "hod" else people
    grid = day_grid(session, ups, {r["code"].upper() for r in grid_rows})
    week = trend(ups, grid, [r["code"].upper() for r in main_rows])
    past = [t["pct"] for t in week[:-1] if t["pct"] is not None]
    week_avg = round(sum(past) / len(past), 1) if past else None

    def recent(code: str, n: int = HISTORY_DAYS) -> list[dict]:
        g = grid.get(code.upper(), {})
        return [g[d] for _, d in reversed(ups) if d in g][:n]

    def pending_row(r: dict) -> dict:
        pend = [p for p in (r.get("permission") or "").split("; ") if p.startswith("Pending")]
        when = pend[0][len("Pending"):].strip() if pend else ""
        return dict(r, reason=f"Short leave requested{(' ' + when) if when else ''} - waiting for approval", pattern=None,
                    action="Approve or reject it in Pocket HRMS")

    blocks = {
        "kind": kind,
        "team": team_c, "team_change": change(team_c, before(s["team"]) if team_c else None),
        "team_headline": headline(team_c, "your team", day) if kind == "hod" else None,
        "team_attention": team_att[:60], "team_attention_more": max(0, len(team_att) - 60),
        "summary": summary_c, "summary_change": change(summary_c, before(s["summary"]) if summary_c else None),
        "summary_headline": headline(summary_c, "your wider team", day) if kind == "hod" else None,
        "dept_patterns": sorted(dept_patterns, key=lambda p: p["name"])[:25],
        "company": company_c, "company_change": change(company_c, before(s["company"]) if company_c else None),
        "company_headline": headline(company_c, "the company", day) if kind == "director" else None,
        "exceptions": s["exceptions"][:200], "exceptions_more": max(0, len(s["exceptions"]) - 200),
        "previous_day": prev_up.report_date.strftime(settings.app.date_format) if prev_up else None,
        "trend": week if sum(1 for t in week if t["pct"] is not None) >= 2 else [], "week_avg": week_avg,
        "pending": [], "watch": [], "teams": [], "concerns": [], "hr_groups": [],
        "main_before": before(main_rows) if main_rows else None,     # full counts of the previous report day (Excel summary)
    }
    if kind == "hod":
        blocks["pending"] = [pending_row(r) for r in _sort_attention_first(people)
                             if "PERMISSION_PENDING" in r["flags"] and not attention(r)]
        shown = {r["code"] for r in team_att} | {r["code"] for r in blocks["dept_patterns"]}
        blocks["watch"] = [dict(r, reason=note, pattern=None, action="Have a word - a pattern is forming")
                           for r in sorted(people, key=lambda x: x["name"])
                           if r["code"] not in shown and (note := week_note(recent(r["code"])))][:20]
    else:
        blocks["teams"] = team_table(s["company"], lambda rs: before(rs))
    if kind == "director":
        c = company_c or {}
        concerns = []
        weak = [t for t in blocks["teams"] if t["pct"] is not None and t["pct"] < 75 and t["people"] >= 3]
        for t in weak[:3]:
            concerns.append({"kind": "bad", "text": f"{t['name']}'s team: {t['pct']:g}% attendance ({t['absent']} of {t['people']} absent)."})
        streaks = sorted(((absent_streak(recent(r["code"])), r["name"]) for r in s["company"]), reverse=True)
        streaks = [(n, nm) for n, nm in streaks if n >= STREAK_ALERT]
        if streaks:
            names = ", ".join(f"{nm} ({n})" for n, nm in streaks[:4])
            concerns.append({"kind": "bad", "text": f"{len(streaks)} people absent {STREAK_ALERT}+ report days in a row: {names}"
                                                    + (" and others." if len(streaks) > 4 else ".")})
        if c.get("attendance_pct") is not None and week_avg is not None:
            d = round(c["attendance_pct"] - week_avg, 1)
            concerns.append({"kind": "good" if d >= 0 else "warn",
                             "text": f"Attendance {c['attendance_pct']:g}% against a {len(past)}-day average of {week_avg:g}% "
                                     f"({'+' if d >= 0 else ''}{d:g} pts)."})
        if c.get("late"):
            top = max(blocks["teams"], key=lambda t: t["late"])
            concerns.append({"kind": "warn", "text": f"{c['late']} late arrivals; most in {top['name']}'s team ({top['late']})."})
        if c.get("missing_punch"):
            concerns.append({"kind": "info", "text": f"{c['missing_punch']} missing punch(es) - HR is following up for regularisation."})
        blocks["concerns"] = concerns[:6]
    if kind == "hr":
        held = [x for x in s["exceptions"] if x["issue"] != NOT_IN_MASTER]
        groups = [
            ("not_in_master", "Not in the employee master",
             "They are in Pocket HRMS but not in the employee master, so no manager receives their attendance.",
             "Add them on the Employees screen with their HOD, or mark them as left.",
             [dict(x, detail=x["status_label"]) for x in s["exceptions"] if x["issue"] == NOT_IN_MASTER]),
            ("routing", "Routing problems", "Their HOD's email cannot be used, so their attendance comes to HR instead.",
             "Correct the HOD email on the Employees screen (or in the routing workbook).",
             [dict(x, detail=issue_text(x["issue"])) for x in held]),
            ("permissions", "Short-leave requests waiting for approval", "Pending requests do not excuse late arrival or early leaving.",
             "Remind the HOD to approve or reject them in Pocket HRMS.",
             [dict(r, detail=pending_row(r)["reason"].replace(" - waiting for approval", "")) for r in s["company"]
              if "PERMISSION_PENDING" in r["flags"]]),
            ("onduty", "On-duty / work from home requests waiting for approval",
             "Until a request is approved, the person is shown as Pocket HRMS has them (usually absent).",
             "Remind the HOD to approve or reject them in Pocket HRMS.",
             [dict(r, detail=onduty_pending_text(r)[0].upper() + onduty_pending_text(r)[1:]) for r in s["company"]
              if "ON_DUTY_PENDING" in r["flags"]]),
            ("missing", "Missing punches", "Only one punch was recorded for the day.",
             "Get them regularised in Pocket HRMS before payroll.",
             [dict(r, detail=("In " + (analysis.t12(r["in_time"]) or "") + " · no out-punch") if r.get("in_time") and not r.get("out_time")
                   else ("Out " + (analysis.t12(r["out_time"]) or "") + " · no in-punch") if r.get("out_time") else "No punch time")
              for r in s["company"] if r["status"] == "MISSING_PUNCH"]),
            ("streaks", f"Absent {STREAK_ALERT}+ report days in a row", "No leave is recorded for these days.",
             "Check with the HOD; record the leave or start the absence process.",
             [dict(r, detail=f"Absent {n} report days in a row") for r in s["company"] if (n := absent_streak(recent(r["code"]))) >= STREAK_ALERT]),
        ]
        blocks["hr_groups"] = [{"key": k, "title": t, "why": w, "action": a, "rows": sorted(rs, key=lambda x: (x.get("hod") or "", x["name"]))}
                               for k, t, w, a, rs in groups if rs]
        blocks["hr_total"] = sum(len(g["rows"]) for g in blocks["hr_groups"])
        short = {"not_in_master": "not in the employee master", "routing": "routing problem(s)", "permissions": "short-leave request(s) pending",
                 "onduty": "on-duty request(s) pending",
                 "missing": "missing punch(es)", "streaks": f"absent {STREAK_ALERT}+ days in a row"}
        blocks["hr_summary"] = ", ".join(f"{len(g['rows'])} {short[g['key']]}" for g in blocks["hr_groups"])
    greeting = "Dear HR team" if kind == "hr" else f"Dear {item.recipient_name}"
    stem = f"Attendance_{item.report_date:%Y-%m-%d}_{''.join(ch if ch.isalnum() else '_' for ch in item.recipient_name).strip('_')}"
    html = _env.get_template("mail.html").render(subject=item.subject, day=day, greeting=greeting, role=item.role,
                                                 company=settings.app.company, b=blocks, app_url=settings.app.public_url,
                                                 attach_name=f"{stem}.xlsx" if cfg.attach_excel else None,
                                                 dashboard_name=f"{stem}_dashboard.html" if cfg.attach_dashboard else None,
                                                 hr_contact=(cfg.hr_emails or [None])[0])
    text = _text(item, day, greeting, blocks)
    attachments = []
    dash_people = people if kind == "hod" else s["company"]
    notes = {r["code"].upper(): p for r in dash_people if (p := pattern(hist.get(r["code"].upper(), [])) or week_note(recent(r["code"])))}
    from daily import pack30
    rules_ = get_rules(session, settings)
    pk = pack30.pack(session, item.report_date, {r["code"].upper() for r in dash_people},
                     {r["code"].upper(): (r.get("hod") or "No HOD") for r in dash_people} if kind != "hod" else None,
                     rules_.single_punch_counts_present) if dash_people else None
    if cfg.attach_excel:
        from daily import daily_excel

        attachments.append(Attachment(f"{stem}.xlsx", daily_excel.build(settings, item, kind, s, blocks, ups, grid, notes, pk), XLSX))
    if cfg.attach_dashboard and dash_people:
        prev_people = [dict(r, status=prev_rows[r["code"].upper()]["status"], flags=prev_rows[r["code"].upper()]["flags"])
                       for r in dash_people if r["code"].upper() in prev_rows] if prev_up else None
        attachments.append(Attachment(f"{stem}_dashboard.html",
                                      dashboard(session, settings, item, dash_people, prev_people or None,
                                                prev_up.report_date if prev_up else None, notes,
                                                teams=blocks["teams"] if kind != "hod" else None, pack=pk), "text/html"))
    return html, text, attachments


def _kpi_line(c: dict) -> str:
    return (f"Total {c['total']} | Present {c['present']} | Absent {c['absent']} | Leave {c['leave']} | OD {c['od']} | "
            f"WFH {c['wfh']} | Late {c['late']} | Missing punch {c['missing_punch']}")


def _text(item: MailItem, day: str, greeting: str, b: dict) -> str:
    """Plain-text part of the email (shown by mail apps that do not display HTML)."""
    kind = b.get("kind", "hod")
    title = {"hr": "Daily HR action list", "director": "Daily company attendance"}.get(kind, "Daily team attendance")
    lines = [f"{greeting},", "", f"{title} for {day}.", ""]

    def people(rows: list[dict]) -> list[str]:
        return [f"- {r['code']} {r['name']}: {r['reason']}" + (f" ({r['pattern']})" if r.get("pattern") else "")
                + (f" -> {r['action']}" if r.get("action") else "") for r in rows]

    for key in ("company_headline", "team_headline", "summary_headline"):
        if b.get(key):
            lines.append(b[key])
    if b.get("pending"):
        lines.append(f"Also: {len(b['pending'])} short-leave request(s) waiting for your approval.")
    lines.append("")
    if b.get("trend"):
        lines.append("Last report days: " + " | ".join(f"{t['label']} {t['day']}: " + ("off" if t["pct"] is None else f"{t['pct']:g}%")
                                                       for t in b["trend"]))
        lines.append("")
    if kind == "director" and b["company"]:
        lines += ["COMPANY", _kpi_line(b["company"]), ""]
        if b.get("concerns"):
            lines += ["TOP CONCERNS"] + [f"- {c['text']}" for c in b["concerns"]] + [""]
        if b.get("teams"):
            lines.append("TEAMS AT A GLANCE (weakest first)")
            lines += [f"- {t['name']}: {'-' if t['pct'] is None else str(t['pct']) + '%'} of {t['people']} | absent {t['absent']} | "
                      f"late {t['late']} | missing punch {t['missing_punch']}" for t in b["teams"]]
            lines.append("")
    if kind == "hr":
        if b["company"]:
            lines += [f"Company: {b['company']['attendance_pct']}% attendance, {b['company']['absent']} absent.", ""]
        for i, g in enumerate(b.get("hr_groups", []), start=1):
            lines += [f"{i}. {g['title'].upper()} ({len(g['rows'])})", g["why"], f"Action: {g['action']}"]
            lines += [f"- {r['code']} {r['name']}" + (f" ({r['hod']})" if r.get("hod") else "") + f": {r['detail']}" for r in g["rows"][:40]]
            lines.append("")
        if not b.get("hr_groups"):
            lines += [f"Nothing needs HR action for {day}.", ""]
    if b["team"] and kind != "hr":
        lines += ["DIRECTOR OFFICE STAFF" if kind == "director" else "YOUR TEAM", _kpi_line(b["team"]), ""]
        if b["team_attention"]:
            lines.append("Needs attention:")
            lines += people(b["team_attention"])
            if b["team_attention_more"]:
                lines.append(f"- ... and {b['team_attention_more']} more in the attachment")
        else:
            lines.append(f"Nobody needs attention on {day}.")
        lines.append("")
    if b.get("pending"):
        lines += ["Short-leave requests to approve:"] + people(b["pending"]) + [""]
    if b["summary"]:
        lines += ["YOUR WIDER TEAM (everyone under you)", _kpi_line(b["summary"]), ""]
    if b.get("watch"):
        lines += ["Watch this week (fine on the day, but a pattern is forming):"]
        lines += [f"- {r['code']} {r['name']}: {r['reason']}" for r in b["watch"]] + [""]
    lines += ["The details are in the attached Excel workbook and dashboard.",
              "This is an automated email from the APIS HR Portal. Please do not reply."]
    return "\n".join(lines)


ROSTER_COLS = [("Code", "code", 11), ("Name", "name", 26), ("Needs attention", "reason", 22), ("Status", "status_label", 15),
               ("In", "in_time", 10), ("Out", "out_time", 10), ("Hours (h:mm)", "work_hours", 11), ("Late by (h:mm)", "late_minutes", 10),
               ("Short by (h:mm)", "early_minutes", 11), ("Leave type", "leave_type", 9), ("Permission", "permission", 20),
               ("On duty", "on_duty", 26)]
# (department, HOD, team and reporting manager are not shown in emails)


def roster_xlsx(settings: Settings, item: MailItem, s: dict) -> bytes:
    buf = io.BytesIO()
    wb = xlsxwriter.Workbook(buf, {"in_memory": True, "strings_to_formulas": False, "strings_to_urls": False})
    title = wb.add_format({"bold": True, "font_size": 14, "font_color": "#835415"})
    head = wb.add_format({"bold": True, "font_color": "#FFFFFF", "bg_color": "#835415", "text_wrap": True, "valign": "vcenter"})
    cell = wb.add_format({"border": 1, "border_color": "#ECDFC9"})
    flag = wb.add_format({"border": 1, "border_color": "#ECDFC9", "bg_color": "#FBE4E1"})
    day = item.report_date.strftime(settings.app.date_format)

    def roster(name: str, rows: list[dict], heading: str) -> None:
        ws = wb.add_worksheet(name[:31])
        excel_banner(wb, ws, [w for _, _, w in ROSTER_COLS], heading)
        for j, (h, _, w) in enumerate(ROSTER_COLS):
            ws.write(2, j, h, head)
            ws.set_column(j, j, w)
        for i, r in enumerate(_sort_attention_first(rows), start=3):
            reason = attention(r)
            for j, (_, k, _) in enumerate(ROSTER_COLS):
                v = (reason if k == "reason" else analysis.t12(r.get(k)) if k in ("in_time", "out_time")
                     else analysis.hm(r.get(k)) if k == "work_hours"
                     else analysis.mins_hm(r.get(k)) if k in ("late_minutes", "early_minutes") else r.get(k))
                ws.write(i, j, "" if v in (None, 0) and k in ("late_minutes", "early_minutes", "in_time", "out_time", "work_hours",
                                                              "leave_type", "reason", "permission", "on_duty")
                         else ("" if v is None else v),
                         flag if reason else cell)
        ws.freeze_panes(3, 2)
        if rows:
            ws.autofilter(2, 0, 2 + len(rows), len(ROSTER_COLS) - 1)

    if s["team"]:
        roster("Team roster", s["team"], f"{item.recipient_name} - team attendance - {day}")
    if s["summary"]:
        roster("Wider team roster", s["summary"], f"Everyone under {item.recipient_name} - {day}")
    if s["exceptions"]:
        ws = wb.add_worksheet("Exceptions")
        cols = [("Code", "code", 12), ("Name", "name", 26), ("Issue", "issue", 30),
                (f"Attendance {day}", "status_label", 20), ("Category", "category", 12)]
        excel_banner(wb, ws, [w for _, _, w in cols], f"Records that could not be routed - {day}")
        for j, (h, _, w) in enumerate(cols):
            ws.write(2, j, h, head)
            ws.set_column(j, j, w)
        for i, x in enumerate(s["exceptions"], start=3):
            for j, (_, k, _) in enumerate(cols):
                ws.write(i, j, x.get(k) or "", cell)
    if not wb.worksheets():
        wb.add_worksheet("Roster").write(0, 0, "No employees.")
    wb.close()
    return buf.getvalue()


def dashboard(session: Session, settings: Settings, item: MailItem, people: list[dict], previous_rows: list[dict] | None = None,
              previous_date: date | None = None, patterns: dict[str, str] | None = None, teams: list[dict] | None = None,
              pack: dict | None = None) -> bytes:
    """The HTML dashboard, limited to this recipient's people: key figures, comparison with the previous report day,
    the exceptions with the action expected from the manager, and the full searchable list."""
    from daily.render import dashboard_html_for

    rules = get_rules(session, settings)
    results = [analysis.EmployeeResult(code=r["code"], name=r["name"], category=r.get("category") or "", shift="", in_time=r["in_time"],
                                       out_time=r["out_time"], punches=0, work_minutes=int(r["work_hours"] * 60) if r["work_hours"] else None,
                                       leave_type=r["leave_type"], day_portion=None,
                                       status=r["status"] if r["status"] in analysis.STATUSES else "NOT_TRACKED",
                                       late_minutes=r["late_minutes"], early_minutes=r["early_minutes"], flags=list(r["flags"]),
                                       department=r.get("department"), hod=r.get("hod"), team=r.get("team"), manager=r.get("manager"),
                                       source=r.get("source") or "HRMS", permission=r.get("permission") or None,
                                       on_duty=r.get("on_duty") or None) for r in people]
    summary = analysis.summarize(results, rules)
    # HOD dashboards have no per-team breakdown; the Director's and HR's company dashboards show one bar per HOD's team
    breakdown = {"by": "HOD", "rows": [{"name": t["name"], "attendance_pct": t["pct"], "tracked": t["people"]} for t in teams]} if teams \
        else {"by": "Team", "rows": []}
    return dashboard_html_for(settings.app.company, item.report_date, f"Daily Attendance - {item.recipient_name}", summary,
                              analysis.highlights(summary, {}, rules, None, item.recipient_name),
                              analysis.in_time_buckets(results), breakdown, people, settings.app.date_format,
                              routing_columns=False, recipient=item.recipient_name, previous_rows=previous_rows,
                              previous_date=previous_date, patterns=patterns, company_view=bool(teams), pack=pack)


# ---------------------------------------------------------------------------- sending
def _with_banner(html: str, would: str) -> str:
    """Put a red TEST banner at the top of the email body, naming the real recipient(s)."""
    from markupsafe import escape

    banner = ('<div style="background:#a52a1a;color:#ffffff;padding:10px 16px;font:bold 14px Segoe UI,Arial,sans-serif;">'
              f"TEST EMAIL - in live use this goes to {escape(would)}</div>")
    at = html.find(">", html.find("<body"))
    return html[:at + 1] + banner + html[at + 1:] if at > 0 else banner + html


def _already_delivered(session: Session, item: MailItem, cfg) -> bool:
    return session.scalar(select(MailItem.id).where(MailItem.report_date == item.report_date, MailItem.id != item.id,
                                                    MailItem.recipient_key == item.recipient_key,
                                                    MailItem.status.in_(delivered_statuses(cfg)))) is not None


def send_items(session: Session, settings: Settings, items: list[MailItem], actor: str, force: bool = False) -> list[MailItem]:
    """Send PENDING (and FAILED) items. Each recipient gets at most one email per day unless `force`
    (an explicit resend by an administrator). Failures are retried with a short back-off."""
    cfg = get_email_settings(session, settings)
    outbox = settings.storage.area("outbox") / (items[0].report_date.isoformat() if items else "misc")
    done = []
    for item in items:
        sendable = item.status in sendable_statuses(cfg) or (force and item.status in (DUPLICATE, SENT, SAVED))
        if not sendable:
            continue
        if not force and _already_delivered(session, item, cfg):
            item.status, item.note = DUPLICATE, "Already sent for this day."
            continue
        to = [a.strip() for a in (item.to_addrs or "").split(",") if a.strip()]
        cc = [a.strip() for a in (item.cc_addrs or "").split(",") if a.strip()]
        testing = cfg.test_recipient
        if not to and not testing:
            item.status, item.note = HELD, item.note or "No address."
            continue
        html, text, attachments = render(session, settings, item)
        subject = item.subject
        if testing:
            would = f"To: {', '.join(to) or '(address not set yet)'}" + (f" | CC: {', '.join(cc)}" if cc else "")
            html = _with_banner(html, would)
            text = f"*** TEST EMAIL - in live use this goes to {would} ***\n\n" + text
            subject = f"[TEST] {item.subject}"
            to, cc = [testing], [a for a in cfg.test_cc if a.lower() != testing.lower()]
        bcc = [] if testing else [a for a in dict.fromkeys(x.strip().lower() for x in cfg.always_bcc if x.strip())
                                  if a not in {y.lower() for y in to + cc}]
        message = build_message(cfg.sender or "attendance@localhost", to, subject, html, text, attachments, cc=cc, bcc=bcc,
                                reply_to=cfg.reply_to)
        error = None
        for attempt in range(1, cfg.retry_attempts + 1):
            item.attempts += 1
            try:
                result = send(cfg, message, outbox)
                item.status, item.note, item.outbox_file = result.status, None, result.outbox_file
                if testing:
                    item.status = TEST_SENT
                    who = testing + (f" (CC {', '.join(cc)})" if cc else "")
                    item.note = (f"Test only: {'delivered to' if result.status == SENT else 'saved to the outbox for'} {who}. "
                                 f"The real recipient has not received it.")
                item.sent_at, item.approved_by = now_utc(), actor
                error = None
                break
            except MailError as exc:
                error = str(exc)
                if attempt < cfg.retry_attempts:
                    SLEEP(2 ** attempt)
        if error:
            item.status, item.note = FAILED, error[:500]
        session.add(EmailLog(upload_id=item.upload_id, scope=item.recipient_key[:100], recipients=(", ".join(to + cc) + (f" | BCC: {', '.join(bcc)}" if bcc else ""))[:2000],
                             subject=subject[:300], mode="LIVE" if cfg.mode == "live" else "TEST", status=item.status,
                             error=item.note if item.status == FAILED else None, outbox_file=item.outbox_file, sent_by=actor))
        done.append(item)
    session.flush()
    if done:
        record_activity(session, "MAIL_SEND", "FAILED" if any(i.status == FAILED for i in done) else "SUCCESS", username=actor,
                        detail={"date": done[0].report_date.isoformat(), "mode": cfg.mode, "forced": force,
                                "status": dict(Counter(i.status for i in done))})
    return done


def approve(session: Session, settings: Settings, day: date, actor: str, ids: list[int] | None = None) -> list[MailItem]:
    sendable = sendable_statuses(get_email_settings(session, settings))
    items = [i for i in items_for(session, day) if i.status in sendable and (ids is None or i.id in ids)]
    return send_items(session, settings, items, actor)
