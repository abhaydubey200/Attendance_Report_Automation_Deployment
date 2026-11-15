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
from datetime import date
from pathlib import Path

import xlsxwriter
from jinja2 import Environment, FileSystemLoader, select_autoescape
from sqlalchemy import select
from sqlalchemy.orm import Session

from core.config import Settings
from core.timeutils import now_utc
from daily import analysis, employees, routing
from daily.mailer import Attachment, MailError, build_message, send
from daily.settings_store import get_email_settings, get_rules
from database.models.daily import DayUpload, EmailLog, EmployeeDay, MailItem
from security.audit import record_activity

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
PENDING, SENT, SAVED, FAILED, HELD, DISABLED, DUPLICATE, SUPERSEDED = (
    "PENDING", "SENT", "SAVED", "FAILED", "HELD", "DISABLED", "DUPLICATE", "SUPERSEDED")
DELIVERED = (SENT, SAVED)
NO_RECORD = "NO_RECORD"
NOT_IN_MASTER = "NOT_IN_EMPLOYEE_MASTER"
LABELS = {**analysis.STATUS_LABEL, NO_RECORD: "No attendance record"}
_env = Environment(loader=FileSystemLoader(Path(__file__).parent / "templates"), autoescape=select_autoescape(["html"]))
SLEEP = time.sleep          # patched in tests


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
            "source": e.source or "HRMS", "bizom_status": e.bizom_status or "", "flags": (e.flags or "").split(",") if e.flags else []}
    return out


def _row_for(r: routing.Route, rows: dict[str, dict]) -> dict:
    row = rows.get(r.code.upper())
    if row is None:
        row = {"code": r.code, "name": r.name, "category": "", "status": NO_RECORD, "status_label": LABELS[NO_RECORD], "in_time": None,
               "out_time": None, "work_hours": None, "late_minutes": 0, "early_minutes": 0, "leave_type": None, "source": "",
               "bizom_status": "", "flags": []}
    return {**row, "name": r.name or row["name"], "department": r.department, "hod": r.hod, "team": r.team, "manager": r.manager}


def attention(row: dict) -> str | None:
    """Why this employee needs a look today (None = fine, covered by the counts)."""
    if row["status"] == "ABSENT":
        return "Absent"
    if row["status"] == NO_RECORD:
        return "No attendance record"
    if row["status"] == "MISSING_PUNCH":
        return "Missing punch" + (f", late {row['late_minutes']} min" if "LATE" in row["flags"] else "")
    reasons = []
    if "LATE" in row["flags"]:
        reasons.append(f"Late {row['late_minutes']} min")
    if "LEFT_EARLY" in row["flags"]:
        reasons.append(f"Left early {row['early_minutes']} min")
    return ", ".join(reasons) or None


def counts(rows: list[dict], single_punch_counts: bool = True) -> dict:
    c = Counter(r["status"] for r in rows)
    tracked = len(rows) - c["NOT_TRACKED"] - c["WEEK_OFF"] - c[NO_RECORD]
    present_eq = c["PRESENT"] + c["ON_DUTY"] + c["WFH"] + (c["MISSING_PUNCH"] if single_punch_counts else 0) + 0.5 * c["HALF_DAY"]
    return {"total": len(rows), "present": c["PRESENT"], "absent": c["ABSENT"], "leave": c["LEAVE"] + c["HALF_DAY"],
            "od": c["ON_DUTY"], "wfh": c["WFH"], "late": sum(1 for r in rows if "LATE" in r["flags"]),
            "missing_punch": c["MISSING_PUNCH"], "week_off": c["WEEK_OFF"], "not_tracked": c["NOT_TRACKED"], "no_record": c[NO_RECORD],
            "attendance_pct": round(100 * present_eq / tracked, 1) if tracked else None,
            "attention": sum(1 for r in rows if attention(r))}


def _sort_attention_first(rows: list[dict]) -> list[dict]:
    return sorted(rows, key=lambda r: (attention(r) is None, r.get("department") or "", r["name"]))


# ---------------------------------------------------------------------------- planning
def build_plan(session: Session, settings: Settings, upload: DayUpload, actor: str) -> list[MailItem]:
    """Create today's mail items for this upload. Earlier unsent items of the same day are superseded;
    recipients already sent for the day are marked DUPLICATE (sent once per recipient per day)."""
    cfg = get_email_settings(session, settings)
    day = upload.report_date
    for old in session.scalars(select(MailItem).where(MailItem.report_date == day, MailItem.status.in_((PENDING, FAILED, HELD)))):
        old.status, old.note = SUPERSEDED, "Replaced by a newer upload of this day."
    delivered = {k for (k,) in session.execute(select(MailItem.recipient_key).where(MailItem.report_date == day,
                                                                                   MailItem.status.in_(DELIVERED)))}
    rows = _rows(session, upload.upload_id)
    rs = routing.routes(session, day)
    in_master = {r.code.upper() for r in rs}
    master_codes = {e.code for e in employees.list_all(session)}
    unmatched = [code for code in rows if code not in master_codes]
    recs = routing.recipients(session, cfg, day, rs)
    items = []
    for rec in recs:
        content: dict = {"team": [r.code for r in rec.team], "summary": [r.code for r in rec.summary], "company": rec.company}
        if rec.key == routing.HR:
            content["exceptions"] = ([{"code": r.code, "issue": r.issue or "Held"} for r in rec.team]
                                     + [{"code": code, "issue": NOT_IN_MASTER} for code in sorted(unmatched)])
            if not content["exceptions"]:
                continue                     # HR mail only on days with something to fix
        team_rows = [_row_for(r, rows) for r in rec.team]
        summary_rows = [_row_for(r, rows) for r in rec.summary]
        company_rows = [_row_for(r, rows) for r in rs] if rec.company else []
        c = {"team": counts(team_rows), "summary": counts(summary_rows) if summary_rows else None,
             "company": counts(company_rows) if company_rows else None,
             "exceptions": len(content.get("exceptions", []))}
        status, note = (PENDING, None) if rec.status == "OK" else (rec.status, rec.note)
        if status == PENDING and rec.key in delivered:
            status, note = DUPLICATE, "Already sent for this day (sent once per recipient per day)."
        name = rec.name
        item = MailItem(upload_id=upload.upload_id, report_date=day, recipient_key=rec.key, recipient_name=name, role=rec.role,
                        to_addrs=", ".join(rec.to) or None, cc_addrs=", ".join(rec.cc) or None,
                        subject=f"{cfg.subject_prefix} | {day:%d-%b-%Y} | {name}", content=json.dumps(content),
                        counts=json.dumps(c), status=status, note=note, attempts=0)
        session.add(item)
        items.append(item)
    session.flush()
    record_activity(session, "MAIL_PLAN", "SUCCESS", username=actor,
                    detail={"date": day.isoformat(), "emails": len(items), "status": dict(Counter(i.status for i in items)),
                            "not_in_master": len(unmatched), "in_master": len(in_master)})
    return items


def items_for(session: Session, day: date, include_old: bool = False) -> list[MailItem]:
    stmt = select(MailItem).where(MailItem.report_date == day)
    if not include_old:
        stmt = stmt.where(MailItem.status != SUPERSEDED)
    return list(session.scalars(stmt.order_by(MailItem.id)))


def item_dict(i: MailItem) -> dict:
    c = json.loads(i.counts)
    return {"id": i.id, "report_date": i.report_date.isoformat(), "key": i.recipient_key, "name": i.recipient_name, "role": i.role,
            "to": i.to_addrs or "", "cc": i.cc_addrs or "", "subject": i.subject, "status": i.status, "note": i.note,
            "attempts": i.attempts, "team": c["team"]["total"], "summary": (c.get("summary") or {}).get("total", 0),
            "company": (c.get("company") or {}).get("total", 0), "exceptions": c.get("exceptions", 0),
            "attention": (c["team"]["attention"] if c["team"]["total"] else (c.get("summary") or c.get("company") or {}).get("attention", 0)),
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
    company = pick(list(rs)) if content.get("company") else []
    exceptions = []
    for x in content.get("exceptions", []):
        row = rows.get(x["code"].upper())
        r = rs.get(x["code"])
        exceptions.append({"code": x["code"], "issue": x["issue"], "name": (r.name if r else (row or {}).get("name", "")),
                           "department": (r.department if r else ""), "hod": (r.hod if r else ""),
                           "status_label": (row or {}).get("status_label", LABELS[NO_RECORD]),
                           "source": (row or {}).get("source", ""), "category": (row or {}).get("category", "")})
    return {"team": team, "summary": summary, "company": company, "exceptions": exceptions}


def _group_table(rows: list[dict], key: str, label_of=None) -> list[dict]:
    groups: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        groups[r.get(key) or "—"].append(r)
    out = []
    for name, rs in sorted(groups.items(), key=lambda kv: (-len(kv[1]), kv[0])):
        c = counts(rs)
        out.append({"name": label_of(name, rs) if label_of else name, **c})
    return out


def _team_label(team: str, rs: list[dict]) -> str:
    mgr = Counter(r["manager"] for r in rs if r.get("manager")).most_common(1)
    who = mgr[0][0].title() if mgr and mgr[0][0].isupper() else (mgr[0][0] if mgr else "")
    return f"{team} ({who})" if who and team != employees.DIRECT else team


def render(session: Session, settings: Settings, item: MailItem) -> tuple[str, str, list[Attachment]]:
    """(html, text, attachments) for one mail item."""
    cfg = get_email_settings(session, settings)
    s = _sections(session, item)
    day = item.report_date.strftime(settings.app.date_format)
    team_att = [dict(r, reason=attention(r)) for r in _sort_attention_first(s["team"]) if attention(r)]
    blocks = {
        "team": counts(s["team"]) if s["team"] else None,
        "team_attention": team_att[:60], "team_attention_more": max(0, len(team_att) - 60),
        "summary": counts(s["summary"]) if s["summary"] else None,
        "summary_by_team": _group_table(s["summary"], "team", _team_label) if s["summary"] else [],
        "company": counts(s["company"]) if s["company"] else None,
        "company_by_hod": _group_table(s["company"], "hod") if s["company"] else [],
        "exceptions": s["exceptions"][:200], "exceptions_more": max(0, len(s["exceptions"]) - 200),
    }
    greeting = "Dear HR team" if item.recipient_key == routing.HR else f"Dear {item.recipient_name}"
    stem = f"Attendance_{item.report_date:%Y-%m-%d}_{''.join(ch if ch.isalnum() else '_' for ch in item.recipient_name).strip('_')}"
    html = _env.get_template("mail.html").render(subject=item.subject, day=day, greeting=greeting, role=item.role,
                                                 company=settings.app.company, b=blocks, app_url=settings.app.public_url,
                                                 attach_name=f"{stem}.xlsx" if cfg.attach_excel else None,
                                                 dashboard_name=f"{stem}_dashboard.html" if cfg.attach_dashboard else None)
    text = _text(item, day, greeting, blocks)
    attachments = []
    if cfg.attach_excel:
        attachments.append(Attachment(f"{stem}.xlsx", roster_xlsx(settings, item, s), XLSX))
    people = s["team"] + [r for r in s["summary"] if r["code"] not in {x["code"] for x in s["team"]}]
    if cfg.attach_dashboard and people and item.recipient_key != routing.HR:
        attachments.append(Attachment(f"{stem}_dashboard.html", dashboard(session, settings, item, people), "text/html"))
    return html, text, attachments


def _kpi_line(c: dict) -> str:
    return (f"Total {c['total']} | Present {c['present']} | Absent {c['absent']} | Leave {c['leave']} | OD {c['od']} | "
            f"WFH {c['wfh']} | Late {c['late']} | Missing punch {c['missing_punch']}")


def _text(item: MailItem, day: str, greeting: str, b: dict) -> str:
    lines = [f"{greeting},", "", f"Daily attendance for {day}.", ""]
    if b["team"]:
        lines += ["YOUR TEAM", _kpi_line(b["team"]), ""]
        if b["team_attention"]:
            lines.append("Needs attention:")
            lines += [f"- {r['code']} {r['name']}: {r['reason']}" for r in b["team_attention"]]
            if b["team_attention_more"]:
                lines.append(f"- ... and {b['team_attention_more']} more in the attachment")
        else:
            lines.append("Nobody needs attention today.")
        lines.append("")
    if b["summary"]:
        lines += ["DEPARTMENT SUMMARY (everyone under you)", _kpi_line(b["summary"]), ""]
        lines += [f"- {t['name']}: {t['total']} employees, {t['present']} present, {t['absent']} absent, {t['late']} late"
                  for t in b["summary_by_team"]]
        lines.append("")
    if b["company"]:
        lines += ["COMPANY SUMMARY BY HOD", _kpi_line(b["company"]), ""]
        lines += [f"- {t['name']}: {t['total']} employees, {t['present']} present, {t['absent']} absent, "
                  f"attendance {t['attendance_pct'] if t['attendance_pct'] is not None else '-'}%" for t in b["company_by_hod"]]
        lines.append("")
    if b["exceptions"]:
        lines += ["RECORDS THAT COULD NOT BE ROUTED"]
        lines += [f"- {x['code']} {x['name']}: {x['issue']}" for x in b["exceptions"]]
        lines.append("")
    lines += ["The full list for your team is attached (people needing attention first).",
              "This is an automated email from the APIS Daily Attendance tool. Please do not reply."]
    return "\n".join(lines)


ROSTER_COLS = [("Code", "code", 11), ("Name", "name", 26), ("Needs attention", "reason", 22), ("Status", "status_label", 15),
               ("In", "in_time", 7), ("Out", "out_time", 7), ("Hours", "work_hours", 7), ("Late (min)", "late_minutes", 9),
               ("Left early (min)", "early_minutes", 11), ("Leave type", "leave_type", 9), ("Department", "department", 18),
               ("HOD", "hod", 16), ("Team", "team", 14), ("Reporting manager", "manager", 18), ("Source", "source", 11)]


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
        ws.write(0, 0, heading, title)
        for j, (h, _, w) in enumerate(ROSTER_COLS):
            ws.write(2, j, h, head)
            ws.set_column(j, j, w)
        for i, r in enumerate(_sort_attention_first(rows), start=3):
            reason = attention(r)
            for j, (_, k, _) in enumerate(ROSTER_COLS):
                v = reason if k == "reason" else r.get(k)
                ws.write(i, j, "" if v in (None, 0) and k in ("late_minutes", "early_minutes", "in_time", "out_time", "work_hours",
                                                              "leave_type", "reason") else ("" if v is None else v),
                         flag if reason else cell)
        ws.freeze_panes(3, 2)
        if rows:
            ws.autofilter(2, 0, 2 + len(rows), len(ROSTER_COLS) - 1)

    def table(name: str, groups: list[dict], first: str, heading: str) -> None:
        ws = wb.add_worksheet(name[:31])
        ws.write(0, 0, heading, title)
        cols = [(first, "name", 34), ("Employees", "total", 10), ("Present", "present", 9), ("Absent", "absent", 9),
                ("Leave", "leave", 8), ("OD", "od", 6), ("WFH", "wfh", 6), ("Late", "late", 7), ("Missing punch", "missing_punch", 9),
                ("Week off", "week_off", 8), ("Not tracked", "not_tracked", 9), ("Attendance %", "attendance_pct", 11)]
        for j, (h, _, w) in enumerate(cols):
            ws.write(2, j, h, head)
            ws.set_column(j, j, w)
        for i, g in enumerate(groups, start=3):
            for j, (_, k, _) in enumerate(cols):
                ws.write(i, j, "" if g.get(k) is None else g[k], cell)

    if s["team"]:
        roster("Team roster", s["team"], f"{item.recipient_name} - team attendance - {day}")
    if s["summary"]:
        table("Department summary", _group_table(s["summary"], "team", _team_label), "Team",
              f"Department summary (everyone under {item.recipient_name}) - {day}")
        roster("Department roster", s["summary"], f"Everyone under {item.recipient_name} - {day}")
    if s["company"]:
        table("Company by HOD", _group_table(s["company"], "hod"), "HOD", f"Company summary by HOD - {day}")
    if s["exceptions"]:
        ws = wb.add_worksheet("Exceptions")
        ws.write(0, 0, f"Records that could not be routed - {day}", title)
        cols = [("Code", "code", 12), ("Name", "name", 26), ("Issue", "issue", 30), ("Department", "department", 18),
                ("HOD", "hod", 18), ("Attendance today", "status_label", 18), ("Source", "source", 11)]
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


def dashboard(session: Session, settings: Settings, item: MailItem, people: list[dict]) -> bytes:
    """The interactive HTML dashboard, limited to this recipient's people."""
    from daily.render import dashboard_html_for

    rules = get_rules(session, settings)
    results = [analysis.EmployeeResult(code=r["code"], name=r["name"], category=r.get("category") or "", shift="", in_time=r["in_time"],
                                       out_time=r["out_time"], punches=0, work_minutes=int(r["work_hours"] * 60) if r["work_hours"] else None,
                                       leave_type=r["leave_type"], day_portion=None,
                                       status=r["status"] if r["status"] in analysis.STATUSES else "NOT_TRACKED",
                                       late_minutes=r["late_minutes"], early_minutes=r["early_minutes"], flags=list(r["flags"]),
                                       department=r.get("department"), hod=r.get("hod"), team=r.get("team"), manager=r.get("manager"),
                                       source=r.get("source") or "HRMS") for r in people]
    groups = defaultdict(list)
    for res in results:
        groups[res.team or "—"].append(res)
    sums = {k: analysis.summarize(v, rules) for k, v in groups.items()}
    summary = analysis.summarize(results, rules)
    breakdown = {"by": "Team", "rows": [analysis._breakdown_row(k, v) for k, v in sorted(sums.items())] if len(sums) > 1 else []}
    return dashboard_html_for(settings.app.company, item.report_date, f"Daily Attendance - {item.recipient_name}", summary,
                              analysis.highlights(summary, sums if len(sums) > 1 else {}, rules, None, item.recipient_name),
                              analysis.in_time_buckets(results), breakdown, people, settings.app.date_format)


# ---------------------------------------------------------------------------- sending
def _already_delivered(session: Session, item: MailItem) -> bool:
    return session.scalar(select(MailItem.id).where(MailItem.report_date == item.report_date, MailItem.id != item.id,
                                                    MailItem.recipient_key == item.recipient_key,
                                                    MailItem.status.in_(DELIVERED))) is not None


def send_items(session: Session, settings: Settings, items: list[MailItem], actor: str, force: bool = False) -> list[MailItem]:
    """Send PENDING (and FAILED) items. Each recipient gets at most one email per day unless `force`
    (an explicit resend by an administrator). Failures are retried with a short back-off."""
    cfg = get_email_settings(session, settings)
    outbox = settings.storage.area("outbox") / (items[0].report_date.isoformat() if items else "misc")
    done = []
    for item in items:
        sendable = item.status in (PENDING, FAILED) or (force and item.status in (DUPLICATE, SENT, SAVED))
        if not sendable:
            continue
        if not force and _already_delivered(session, item):
            item.status, item.note = DUPLICATE, "Already sent for this day."
            continue
        to = [a.strip() for a in (item.to_addrs or "").split(",") if a.strip()]
        cc = [a.strip() for a in (item.cc_addrs or "").split(",") if a.strip()]
        if not to:
            item.status, item.note = HELD, item.note or "No address."
            continue
        html, text, attachments = render(session, settings, item)
        message = build_message(cfg.sender or "attendance@localhost", to, item.subject, html, text, attachments, cc=cc,
                                reply_to=cfg.reply_to)
        error = None
        for attempt in range(1, cfg.retry_attempts + 1):
            item.attempts += 1
            try:
                result = send(cfg, message, outbox)
                item.status, item.note, item.outbox_file = result.status, None, result.outbox_file
                item.sent_at, item.approved_by = now_utc(), actor
                error = None
                break
            except MailError as exc:
                error = str(exc)
                if attempt < cfg.retry_attempts:
                    SLEEP(2 ** attempt)
        if error:
            item.status, item.note = FAILED, error[:500]
        session.add(EmailLog(upload_id=item.upload_id, scope=item.recipient_key[:100], recipients=", ".join(to + cc)[:2000],
                             subject=item.subject[:300], mode="LIVE" if cfg.mode == "live" else "TEST", status=item.status,
                             error=item.note if item.status == FAILED else None, outbox_file=item.outbox_file, sent_by=actor))
        done.append(item)
    session.flush()
    if done:
        record_activity(session, "MAIL_SEND", "FAILED" if any(i.status == FAILED for i in done) else "SUCCESS", username=actor,
                        detail={"date": done[0].report_date.isoformat(), "mode": cfg.mode, "forced": force,
                                "status": dict(Counter(i.status for i in done))})
    return done


def approve(session: Session, settings: Settings, day: date, actor: str, ids: list[int] | None = None) -> list[MailItem]:
    items = [i for i in items_for(session, day) if i.status in (PENDING, FAILED) and (ids is None or i.id in ids)]
    return send_items(session, settings, items, actor)
