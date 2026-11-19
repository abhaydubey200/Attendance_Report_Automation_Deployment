"""Month-end: monthly report per team lead / HOD + Director, a permanent summary, a full archive, then a guarded cleanup.

Sequence (Automation screen or ``main.py monthly`` / ``main.py cleanup``):
  1. generate  - monthly KPIs per recipient (same routing as the daily emails), summary row, archive .xlsx of every
                 daily row of the month; monthly emails prepared (sent now in auto mode, else approved on screen).
  2. backup    - the normal daily backup job (must succeed AFTER the archive).
  3. cleanup   - only for months older than jobs.keep_months, only when the archive file is intact and a later
                 backup succeeded: removes that month's daily employee rows and stored upload files. The summary,
                 the employee master, settings, email and job logs are kept.

Attendance % is a workforce-availability indicator, not a measure of productivity (said in the Excel and dashboard).
"""

from __future__ import annotations

import calendar
import io
import json
import shutil
from collections import Counter, defaultdict
from datetime import date, timedelta
from pathlib import Path

import xlsxwriter
from jinja2 import Environment, FileSystemLoader, select_autoescape
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from core.config import Settings
from core.timeutils import now_utc
from daily import jobs, mail, month_insights, reports, routing
from daily import analysis
from daily.analysis import hm
from daily.branding import excel_banner
from daily.mailer import Attachment
from daily.settings_store import get_email_settings, get_rules
from database.connection import session_scope
from database.models.daily import DayUpload, EmployeeDay, JobRun, MailItem, MonthlySummary
from ingestion.checksum import sha256_bytes

PREFIX = "MONTHLY:"
XLSX = mail.XLSX
_env = Environment(loader=FileSystemLoader(Path(__file__).parent / "templates"), autoescape=select_autoescape(["html"]))
_env.filters["t12"] = analysis.t12
STATUS_CODE = {"PRESENT": "P", "MISSING_PUNCH": "MP", "ON_DUTY": "OD", "WFH": "WFH", "HALF_DAY": "HD", "LEAVE": "L",
               "ABSENT": "A", "WEEK_OFF": "WO", "HOLIDAY": "HO", "NOT_TRACKED": "-", mail.NO_RECORD: ""}
ATTENTION = {"absent": 3, "late": 5, "missing_punch": 3}       # monthly thresholds for "needs attention"


def previous_month(today: date | None = None) -> str:
    first = (today or jobs.yesterday_ist() + timedelta(days=1)).replace(day=1)
    return (first - timedelta(days=1)).strftime("%Y-%m")


def month_bounds(month: str) -> tuple[date, date]:
    y, m = (int(x) for x in month.split("-"))
    return date(y, m, 1), date(y, m, calendar.monthrange(y, m)[1])


def label(month: str) -> str:
    return month_bounds(month)[0].strftime("%b-%Y")


# ---------------------------------------------------------------------------- data
def _days(session: Session, month: str) -> dict[date, int]:
    start, end = month_bounds(month)
    return {d: u for d, u in session.execute(select(DayUpload.report_date, DayUpload.upload_id).where(
        DayUpload.is_current.is_(True), DayUpload.report_date >= start, DayUpload.report_date <= end).order_by(DayUpload.report_date))}


def _rows_by_code(session: Session, month: str) -> tuple[list[date], dict[str, dict[date, dict]]]:
    days = _days(session, month)
    by_code: dict[str, dict[date, dict]] = defaultdict(dict)
    upload_day = {u: d for d, u in days.items()}
    for e in session.scalars(select(EmployeeDay).where(EmployeeDay.upload_id.in_(list(days.values()) or [-1]))):
        by_code[e.employee_code.upper()][upload_day[e.upload_id]] = reports.day_dict(upload_day[e.upload_id], e)
    return sorted(days), by_code


def _person(code: str, name: str, route: routing.Route | None, per_day: dict[date, dict], rules) -> dict:
    days = list(per_day.values())
    t = reports._tally(days, rules)
    t["wfh"] = sum(1 for d in days if d["status"] == "WFH")
    t["od"] = sum(1 for d in days if d["status"] == "ON_DUTY")
    t["pending"] = sum(1 for d in days if "PERMISSION_PENDING" in d["flags"])     # short-leave requests not yet approved
    last = days[-1] if days else {}
    reasons = [f"{t[k]} {k.replace('_', ' ')}" for k, n in ATTENTION.items() if t.get(k, 0) >= n]
    return {"code": code, "name": name or last.get("name", ""), "department": (route.department if route else last.get("department", "")),
            "hod": route.hod if route else last.get("hod", ""), "team": route.team if route else last.get("team", ""),
            "manager": route.manager if route else last.get("manager", ""), **t, "reason": ", ".join(reasons),
            "codes": {d.isoformat(): STATUS_CODE.get(v["status"], "?") for d, v in per_day.items()}}


MIN_WORKING_SHARE = 0.2      # a day counts as a working day when at least 20% of the people on it were due to work
NO_HOD = "No HOD assigned"


def _scope_totals(people: list[dict], days: list[date], by_code: dict, rules) -> dict:
    all_days = [d for p in people for d in by_code.get(p["code"].upper(), {}).values()]
    t = reports._tally(all_days, rules)
    t.update(employees=len(people), working_days=len(days), wfh=sum(p["wfh"] for p in people), od=sum(p["od"] for p in people))
    trend = []
    for d in days:
        day_rows = [by_code.get(p["code"].upper(), {}).get(d) for p in people]
        present = [r for r in day_rows if r]
        dt = reports._tally(present, rules)
        # A Sunday or holiday where only a handful of people were due (one punch, one stray "A") is not a working day:
        # it is left out of the trend and the working-day count (those people still count in the totals).
        working = dt["tracked"] > 0 and dt["tracked"] >= MIN_WORKING_SHARE * len(present)
        trend.append({"date": d.isoformat(), "attendance_pct": dt["attendance_pct"] if working else None})
    t["trend"] = trend
    t["work_days"] = sum(1 for x in trend if x["attendance_pct"] is not None)   # days most people were due to work
    return t


def _groups(people: list[dict], key: str) -> list[dict]:
    g: dict[str, list[dict]] = defaultdict(list)
    for p in people:
        g[p[key] or NO_HOD].append(p)
    out = []
    for name, ps in sorted(g.items(), key=lambda kv: (-len(kv[1]), kv[0])):
        tracked = sum(p["tracked"] for p in ps)
        present_eq = sum((p["attendance_pct"] or 0) * p["tracked"] / 100 for p in ps)
        out.append({"name": name, "employees": len(ps), "absent": sum(p["absent"] for p in ps), "late": sum(p["late"] for p in ps),
                    "missing_punch": sum(p["missing_punch"] for p in ps), "leave": sum(p["leave"] + p["half_day"] for p in ps),
                    "attendance_pct": round(100 * present_eq / tracked, 1) if tracked else None,
                    "attention": sum(1 for p in ps if p["reason"])})
    return out


def team_table(people: list[dict], prev_people: dict[str, dict] | None) -> list[dict]:
    """Director / HR: one row per HOD's team, best attendance first, with the change vs last month (same people)."""
    rows = _groups(people, "hod")
    before = {g["name"]: g for g in _groups(list(prev_people.values()), "hod")} if prev_people else {}
    for g in rows:
        b = before.get(g["name"])
        g["before"] = b["attendance_pct"] if b else None
        g["change"] = (round(g["attendance_pct"] - b["attendance_pct"], 1)
                       if b and b["attendance_pct"] is not None and g["attendance_pct"] is not None else None)
    rows.sort(key=lambda g: (g["attendance_pct"] is None, -(g["attendance_pct"] or 0), g["name"]))
    for n, g in enumerate(rows, start=1):
        g["rank"] = n
    return rows


ACTION_GROUPS = [  # key, heading in the email, colour
    ("talk", "Speak to them about repeated absences", "#b91c1c"),
    ("payroll", "Regularise missing punches before payroll", "#6d28d9"),
    ("punctuality", "Counsel on punctuality", "#b45309"),
]


def action_group(p: dict) -> str:
    if p["absent"] >= ATTENTION["absent"]:
        return "talk"
    if p["missing_punch"] >= ATTENTION["missing_punch"]:
        return "payroll"
    return "punctuality"


def director_concerns(teams: list[dict], ins: dict, totals: dict, attention: list[dict]) -> list[str]:
    """The Director's short list of what needs a decision or a word with an HOD."""
    out = []
    weak = [g for g in teams if g["attendance_pct"] is not None and g["attendance_pct"] < 85 and g["employees"] >= 3]
    if weak:
        out.append(f"{len(weak)} team{'s' if len(weak) != 1 else ''} below 85% attendance: "
                   + ", ".join(f"{g['name']} ({g['attendance_pct']:g}%)" for g in weak[:5]) + ".")
    slipped = [g for g in teams if g["change"] is not None and g["change"] <= -5]
    if slipped:
        out.append("Slipped 5+ pts on last month: " + ", ".join(f"{g['name']} ({g['before']:g}% → {g['attendance_pct']:g}%)"
                                                               for g in sorted(slipped, key=lambda g: g["change"])[:5]) + ".")
    if ins["streaks"]:
        n = len(ins["streaks"])
        out.append(f"{n} employee{'s were' if n != 1 else ' was'} absent 3+ report days in a row.")
    if attention:
        n = len(attention)
        out.append(f"{n} employee{'s have' if n != 1 else ' has'} a recurring absence, late-arrival or missing-punch pattern.")
    if totals.get("missing_punch"):
        out.append(f"{totals['missing_punch']} missing punches to be regularised before payroll.")
    return out


def routing_issue_text(issue: str | None) -> str:
    text = issue or ""
    for code, plain in (("HOD_EMAIL_CONFLICT", "Two different HOD emails"), ("NO_HOD_EMAIL", "No HOD email"),
                        ("NOT_IN_EMPLOYEE_MASTER", "Not in the employee master")):
        if text.startswith(code):
            return plain
    return text or "Held for HR"


def hr_checklist(people: list[dict], ins: dict, held: list[dict]) -> list[dict]:
    """HR's month-end payroll checklist: numbered groups, most urgent first. Each row: name, code, team, detail."""
    def rows(ps, detail):
        return [{"name": p["name"], "code": p["code"], "team": p.get("hod") or NO_HOD, "detail": detail(p)} for p in ps]

    def n(x, word, many=None):
        return f"{x} {word if x == 1 else (many or word + 's')}"
    mp = sorted([p for p in people if p["missing_punch"]], key=lambda p: (-p["missing_punch"], p["name"]))
    ab = sorted([p for p in people if p["absent"]], key=lambda p: (-p["absent"], p["name"]))
    pend = sorted([p for p in people if p.get("pending")], key=lambda p: (-p["pending"], p["name"]))
    by_code = {p["code"].upper(): p for p in people}
    groups = [
        ("mp", "Missing punches to regularise", "Regularise in Pocket HRMS so the day is paid correctly.", "#6d28d9",
         rows(mp, lambda p: n(p["missing_punch"], "missing punch", "missing punches")), sum(p["missing_punch"] for p in mp)),
        ("absent", "Absent days to confirm: leave or loss of pay", "Check whether leave was applied; otherwise mark loss of pay.", "#b91c1c",
         rows(ab, lambda p: n(p["absent"], "absent day")), sum(p["absent"] for p in ab)),
        ("pending", "Short-leave requests still pending", "Ask the manager to approve or reject them in Pocket HRMS.", "#0369a1",
         rows(pend, lambda p: n(p["pending"], "request")), sum(p["pending"] for p in pend)),
        ("streak", "Long absence runs (3+ report days in a row)", "Confirm the reason with the HOD; long leave may need approval.", "#b45309",
         [{"name": x["name"], "code": x["code"], "team": (by_code.get(x["code"].upper()) or {}).get("hod") or NO_HOD,
           "detail": f"{x['days']} days, {x['from']:%d %b} – {x['to']:%d %b}"} for x in ins["streaks"]], len(ins["streaks"])),
        ("routing", "Employees whose report has no HOD to go to", "Fix the HOD email in Employee mapping so their manager gets their report.",
         "#475569", [{"name": h["name"], "code": h["code"], "team": "-", "detail": routing_issue_text(h["issue"])} for h in held], len(held)),
    ]
    return [{"key": k, "title": t, "how": how, "color": c, "rows": r, "total": tot} for k, t, how, c, r, tot in groups]


def _planning(scope_people: list[dict], groups: list[dict]) -> list[str]:
    notes = []
    weak = [g for g in groups if g["attendance_pct"] is not None and g["attendance_pct"] < 85 and g["employees"] >= 3]
    if weak:
        notes.append("Teams needing attention (attendance below 85%): " + ", ".join(f"{g['name']} ({g['attendance_pct']}%)" for g in weak[:8]) + ".")
    recurring = [p for p in scope_people if p["reason"]]
    if recurring:
        notes.append(f"{len(recurring)} employee(s) with recurring absence / late / missing-punch patterns - see the attachment.")
    mp = sum(p["missing_punch"] for p in scope_people)
    if mp:
        notes.append(f"{mp} missing punch(es) this month - make sure they are regularised before payroll.")
    notes.append(f"Workforce strength going into next month: {len(scope_people)} employees.")
    return notes


# ---------------------------------------------------------------------------- generate
def generate(settings: Settings, engine, month: str | None = None, mode: str | None = None, trigger: str = "SCHEDULED",
             actor: str = "scheduler") -> dict:
    month = month or previous_month()
    with jobs.job_lock(settings, "monthly"):
        with session_scope(engine) as s:
            run_id = jobs.start_job(s, "MONTHLY", month, trigger, actor).id
        try:
            with session_scope(engine) as s:
                result = _generate(s, settings, month, mode, actor)
                jobs.finish_job(s, s.get(JobRun, run_id), result["status"], result, result.get("problem"))
                if result["status"] != jobs.SUCCESS:
                    jobs.alert(s, settings, f"Monthly attendance {label(month)}: {result['status'].lower()}",
                               result.get("problem") or "")
            return {"run_id": run_id, **result}
        except Exception as exc:
            with session_scope(engine) as s:
                jobs.finish_job(s, s.get(JobRun, run_id), jobs.FAILED, None, f"{type(exc).__name__}: {exc}")
                jobs.alert(s, settings, f"Monthly attendance {label(month)}: failed", f"{type(exc).__name__}: {exc}")
            raise


def _generate(s: Session, settings: Settings, month: str, mode: str | None, actor: str) -> dict:
    from daily import service

    rules = get_rules(s, settings)
    cfg = get_email_settings(s, settings)
    days, by_code = _rows_by_code(s, month)
    if not days:
        return {"status": jobs.FAILED, "month": month, "problem": f"No uploaded days in {label(month)}."}
    end = month_bounds(month)[1]
    rs = routing.routes(s, end)
    route_of = {r.code.upper(): r for r in rs}
    names = {code: next(iter(v.values()))["name"] for code, v in by_code.items()}
    people = {code: _person(code, names.get(code, ""), route_of.get(code), by_code.get(code, {}), rules)
              for code in set(by_code) | set(route_of) if by_code.get(code)}
    everyone = sorted(people.values(), key=lambda p: (p["department"], p["name"]))
    company = _scope_totals(everyone, days, by_code, rules)
    by_hod = _groups(everyone, "hod")

    # permanent summary + archive of every daily row of the month
    start = month_bounds(month)[0]
    f = reports.Filters(start=start, end=end)
    full = reports.attendance_report(s, f, rules, with_days=True)
    archive_dir = settings.storage.area("archive")
    archive_dir.mkdir(parents=True, exist_ok=True)
    archive = archive_dir / f"attendance_{month}.xlsx"
    content = reports.attendance_excel(settings.app.company, full, f, settings.app.date_format)
    archive.write_bytes(content)
    summary_row = s.get(MonthlySummary, month) or MonthlySummary(month=month)
    summary_row.days, summary_row.employees = len(days), len(everyone)
    summary_row.attendance_pct = None if company["attendance_pct"] is None else str(company["attendance_pct"])
    summary_row.summary = json.dumps({"company": company, "by_hod": by_hod, "days": [d.isoformat() for d in days]}, default=str)
    summary_row.archive_path, summary_row.archive_sha256 = str(archive), sha256_bytes(content)
    summary_row.status, summary_row.generated_by, summary_row.generated_at = "ARCHIVED", actor, now_utc()
    s.add(summary_row)

    # monthly emails: one per recipient, same routing as the daily emails
    for old in s.scalars(select(MailItem).where(MailItem.recipient_key.like(f"{PREFIX}%"), MailItem.report_date == end,
                                                MailItem.status.in_((mail.HELD, mail.DUPLICATE, mail.DISABLED) + mail.sendable_statuses(cfg)))):
        old.status, old.note = mail.SUPERSEDED, "Replaced by a newer monthly run."
    delivered = {k for (k,) in s.execute(select(MailItem.recipient_key).where(MailItem.report_date == end,
                                                                              MailItem.status.in_(mail.delivered_statuses(cfg))))}
    last_upload = _days(s, month)[days[-1]]
    items = []
    for rec in routing.recipients(s, cfg, end, rs):
        is_hr = rec.key == routing.HR
        kind = "hr" if is_hr else "director" if rec.company else "hod"
        # HR gets the company-wide payroll checklist; the people held for HR are listed as routing problems, not as a team
        held = [{"code": r.code, "name": r.name, "issue": r.issue or r.rule} for r in rec.team] if is_hr else []
        team = [] if is_hr else [r.code for r in rec.team if r.code.upper() in people]
        summ = [r.code for r in rec.summary if r.code.upper() in people]
        company_wide = rec.company or is_hr
        if not team and not summ and not company_wide:
            continue
        scope = everyone if company_wide else [people[c.upper()] for c in dict.fromkeys(team + summ)]
        totals = _scope_totals(scope, days, by_code, rules)
        status, note = (mail.PENDING, None) if rec.status == "OK" else (rec.status, rec.note)
        if status == mail.HELD and cfg.test_recipient:
            status, note = mail.PENDING, f"Testing: {rec.note}"
        if status == mail.PENDING and f"{PREFIX}{rec.key}" in delivered:
            status, note = mail.DUPLICATE, "Monthly report already sent."
        item = MailItem(upload_id=last_upload, report_date=end, recipient_key=f"{PREFIX}{rec.key}", recipient_name=rec.name,
                        role=f"Monthly - {rec.role}", to_addrs=", ".join(rec.to) or None, cc_addrs=", ".join(rec.cc) or None,
                        subject=f"Monthly Attendance | {label(month)} | {rec.name}",
                        content=json.dumps({"kind": "monthly", "month": month, "team": team, "summary": summ, "company": company_wide,
                                            "view": kind, "held": held}),
                        counts=json.dumps({"team": {"total": len(scope), "attention": sum(1 for p in scope if p["reason"]),
                                                    "attendance_pct": totals["attendance_pct"]},
                                           "summary": None, "company": None, "exceptions": 0}),
                        status=status, note=note, attempts=0)
        s.add(item)
        items.append(item)
    s.flush()
    mode = mode or service.default_send_mode(cfg)
    pending = [i for i in items if i.status == mail.PENDING]
    for i in pending:                       # verify every email before sending any
        render(s, settings, i)
    if mode == service.AUTO and pending:
        mail.send_items(s, settings, pending, actor)
    counts = dict(Counter(i.status for i in items))
    result = {"status": jobs.PARTIAL if counts.get(mail.FAILED) else jobs.SUCCESS, "month": month, "days": len(days),
              "employees": len(everyone), "attendance_pct": company["attendance_pct"], "archive": str(archive),
              "emails": counts, "send_mode": mode}
    if counts.get(mail.FAILED):
        result["problem"] = f"{counts[mail.FAILED]} monthly email(s) failed."
    return result


# ---------------------------------------------------------------------------- render (called by mail.render)
def render(session: Session, settings: Settings, item: MailItem) -> tuple[str, str, list[Attachment]]:
    c = json.loads(item.content)
    month = c["month"]
    rules = get_rules(session, settings)
    days, by_code = _rows_by_code(session, month)
    end = month_bounds(month)[1]
    route_of = {r.code.upper(): r for r in routing.routes(session, end)}
    people_all = {code: _person(code, next(iter(v.values()))["name"], route_of.get(code), v, rules) for code, v in by_code.items()}
    pick = lambda codes: [people_all[x.upper()] for x in codes if x.upper() in people_all]  # noqa: E731
    team, summ = pick(c["team"]), pick(c["summary"])
    company = sorted(people_all.values(), key=lambda p: (p["department"], p["name"])) if c.get("company") else []
    view = c.get("view") or ("director" if company else "hod")       # hod | director | hr
    scope = company or list({p["code"]: p for p in team + summ}.values())
    totals = _scope_totals(scope, days, by_code, rules)
    cfg = get_email_settings(session, settings)
    prev, prev_attention, prev_people, prev_trend = _previous(session, settings, month, {p["code"].upper() for p in scope}, rules)
    who = "the company" if company else "your team"
    ins = month_insights.build(scope, days, by_code, rules, totals, prev, prev_people, who)
    # HOD emails never name HODs, teams or managers; the Director's and HR's show a team-by-team table by HOD
    teams = team_table(scope, prev_people) if company else []
    attention = sorted([p for p in scope if p["reason"]], key=lambda p: (-p["absent"], -p["missing_punch"], -p["late"], p["name"]))
    for p in scope:
        b = (prev_people or {}).get(p["code"].upper())
        p["before"] = b["attendance_pct"] if b else None
        p["change"] = (round(p["attendance_pct"] - b["attendance_pct"], 1)
                       if b and b["attendance_pct"] is not None and p["attendance_pct"] is not None else None)
        p["action"] = monthly_action(p)[0] if p["reason"] else ""
    limit = 12 if view == "director" else 40
    groups_of = [{"key": k, "title": t, "color": col, "people": [p for p in attention[:limit] if action_group(p) == k]}
                 for k, t, col in ACTION_GROUPS]
    blocks = {"totals": totals, "group_by": "HOD" if company else "Team", "groups": teams, "attention": attention[:limit],
              "attention_more": max(0, len(attention) - limit), "planning": _planning(scope, teams),
              "team_size": len(team), "is_director": view == "director", "view": view, "action_groups": [g for g in groups_of if g["people"]],
              "weeks": ins["weeks"], "perfect": ins["perfect"], "improved": ins["improved"][:5], "declined": ins["declined"][:5],
              "concerns": director_concerns(teams, ins, totals, attention) if view == "director" else [],
              "checklist": hr_checklist(scope, ins, c.get("held") or []) if view == "hr" else [],
              "held": c.get("held") or []}
    greeting = "Dear HR team" if view == "hr" else f"Dear {item.recipient_name}"
    stem = f"Monthly_Attendance_{month}_{''.join(ch if ch.isalnum() else '_' for ch in item.recipient_name).strip('_')}"
    title = {"hod": "Monthly Team Attendance Report", "director": "Monthly Company Attendance Report",
             "hr": "Monthly HR Payroll Checklist"}[view]
    html = _env.get_template("monthly.html").render(subject=item.subject, month=label(month), month_long=month_bounds(month)[0].strftime("%B %Y"),
                                                    greeting=greeting, company=settings.app.company, b=blocks, title=title,
                                                    attach_name=f"{stem}.xlsx" if cfg.attach_excel else None,
                                                    dashboard_name=f"{stem}_dashboard.html" if cfg.attach_dashboard and scope else None,
                                                    thresholds=ATTENTION, prev=prev, prev_month=label(previous_month_of(month)),
                                                    prev_attention=prev_attention, attention_total=len(attention),
                                                    avg_hours=hm(totals.get("avg_work_hours")), ins=ins, who=who)
    files = []
    if cfg.attach_excel:
        files.append(Attachment(f"{stem}.xlsx", _xlsx(settings, item, month, days, scope, totals, teams, blocks, ins), XLSX))
    if cfg.attach_dashboard and scope:
        files.append(Attachment(f"{stem}_dashboard.html",
                                dashboard_html(settings, item, month, days, scope, totals, blocks, by_code, prev, prev_people,
                                               prev_trend, ins, rules),
                                "text/html"))
    return html, _text(greeting, month, totals, blocks, ins, [f.filename for f in files]), files


def _text(greeting: str, month: str, totals: dict, blocks: dict, ins: dict, attached: list[str]) -> str:
    """Plain-text version of the (short) month-end email, for mail clients that do not show HTML. Details are attached."""
    view = blocks["view"]
    pct = "-" if totals["attendance_pct"] is None else f"{totals['attendance_pct']:g}%"
    lines = [f"{greeting},", "", f"Attendance for {label(month)}: {totals['work_days']} working days, {totals['employees']} employees.",
             f"Average attendance {pct} | Absences {totals['absent']} | Late {totals['late']} | Missing punches {totals['missing_punch']}", ""]
    if view == "hr":
        lines.append("Before payroll:")
        open_checks = [g for g in blocks["checklist"] if g["rows"]]
        if not open_checks:
            lines.append("- Nothing to settle.")
        for n, g in enumerate(open_checks, start=1):
            more = f" + {len(g['rows']) - 5} more" if len(g["rows"]) > 5 else ""
            lines.append(f"{n}. {g['title']} ({len(g['rows'])}): " + ", ".join(f"{r['name']} ({r['detail']})" for r in g["rows"][:5]) + more)
    elif view == "director":
        if blocks["concerns"]:
            lines += ["Needs your attention:"] + [f"- {x}" for x in blocks["concerns"][:4]] + [""]
        teams = blocks["groups"]
        shown = teams if len(teams) <= 10 else teams[:5] + teams[-5:]
        lines += ["Teams (best first" + (", best 5 and weakest 5" if len(teams) > 10 else "") + "):"] + [
            f"{g['rank']}. {g['name']}: {'-' if g['attendance_pct'] is None else str(g['attendance_pct']) + '%'}, {g['absent']} absent" for g in shown]
    else:
        if len(blocks["weeks"]) > 1:
            lines += ["Week by week:"] + [f"- {w['week']} ({w['range']}): {'-' if w['attendance_pct'] is None else str(w['attendance_pct']) + '%'}, "
                                         f"{w['absent']} absent, {w['late']} late, {w['missing_punch']} missing punches" for w in blocks["weeks"]] + [""]
        if blocks["attention"]:
            lines += ["Action required:"] + [f"- {p['name']} ({p['code']}): {p['reason']} - {p['action']}" for p in blocks["attention"][:10]]
            if len(blocks["attention"]) + blocks["attention_more"] > 10:
                lines.append(f"+ {len(blocks['attention']) + blocks['attention_more'] - 10} more in the attachments.")
        else:
            lines.append("Nobody has a recurring absence, late-arrival or missing-punch pattern.")
        for title, rows in (("Slipped 5+ pts vs last month", blocks["declined"]), ("Improved 5+ pts", blocks["improved"])):
            if rows:
                lines += ["", f"{title}: " + ", ".join(f"{x['name']} ({x['before']:g}% -> {x['now']:g}%)" for x in rows)]
        if blocks["perfect"]:
            lines += ["", "Full attendance: " + ", ".join(p["name"] for p in blocks["perfect"][:40])]
    lines += ["", "Automated email from the APIS Daily Attendance tool."]
    return "\n".join(lines)


def _xlsx(settings: Settings, item: MailItem, month: str, days: list[date], people: list[dict], totals: dict, groups: list[dict],
          blocks: dict, ins: dict | None = None) -> bytes:
    """Month-end workbook. Sheet order by recipient:
    HOD      Summary, Insights, Needs attention, Weeks, Employees, Calendar
    Director Summary, Teams, Insights, Needs attention, Weeks, Employees, Calendar
    HR       Summary, Teams, Needs attention, Routing problems, Weeks, Insights, Employees, Calendar"""
    view = blocks.get("view", "hod")
    company = view in ("director", "hr")
    buf = io.BytesIO()
    wb = xlsxwriter.Workbook(buf, {"in_memory": True, "strings_to_formulas": False, "strings_to_urls": False})
    head = wb.add_format({"bold": True, "font_color": "#FFFFFF", "bg_color": "#14213D", "text_wrap": True, "valign": "vcenter",
                          "border": 1, "border_color": "#14213D"})
    cell = wb.add_format({"border": 1, "border_color": "#E6E8EF", "valign": "vcenter"})
    num = wb.add_format({"border": 1, "border_color": "#E6E8EF", "valign": "vcenter", "align": "center"})
    zero = wb.add_format({"border": 1, "border_color": "#E6E8EF", "valign": "vcenter", "align": "center", "font_color": "#B6BCC8"})
    bold = wb.add_format({"border": 1, "border_color": "#E6E8EF", "bold": True, "font_color": "#14213D"})
    flag = wb.add_format({"border": 1, "border_color": "#E6E8EF", "bg_color": "#FDECEC", "valign": "vcenter"})
    wrap = wb.add_format({"border": 1, "border_color": "#E6E8EF", "text_wrap": True, "valign": "vcenter"})
    act = wb.add_format({"border": 1, "border_color": "#F5E3A6", "bg_color": "#FFF8E1", "text_wrap": True, "valign": "vcenter"})
    note = wb.add_format({"italic": True, "font_color": "#5D6577"})
    big = wb.add_format({"border": 1, "border_color": "#E6E8EF", "bold": True, "font_size": 13, "font_color": "#14213D"})
    up = wb.add_format({"border": 1, "border_color": "#E6E8EF", "bold": True, "font_color": "#15803D", "align": "center"})
    down = wb.add_format({"border": 1, "border_color": "#E6E8EF", "bold": True, "font_color": "#B91C1C", "align": "center"})
    pct_fmt = {"good": wb.add_format({"border": 1, "border_color": "#E6E8EF", "bold": True, "font_color": "#15803D", "bg_color": "#F0FAF3"}),
               "warn": wb.add_format({"border": 1, "border_color": "#E6E8EF", "bold": True, "font_color": "#B45309", "bg_color": "#FFF8EB"}),
               "bad": wb.add_format({"border": 1, "border_color": "#E6E8EF", "bold": True, "font_color": "#B91C1C", "bg_color": "#FEF3F2"})}

    def band(v):
        return "good" if v is not None and v >= 90 else "warn" if v is not None and v >= 75 else "bad"

    def chg(v):
        return ("", zero) if v is None else (v, up if v > 0 else down if v < 0 else num)

    day_fmt = {code: wb.add_format({"align": "center", "valign": "vcenter", "bold": True, "font_size": 9, "border": 1,
                                    "border_color": "#FFFFFF", "bg_color": col,
                                    "font_color": "#334155" if code in ("WO", "HO", "-") else "#FFFFFF"})
               for code, _, col in DAY_CODES}
    day_fmt[""] = wb.add_format({"border": 1, "border_color": "#F1F5F9", "bg_color": "#F8FAFC"})
    team_col = [("HOD's team", "hod", 24)] if company else []

    def summary():
        ws = wb.add_worksheet("Summary")
        ws.set_column(0, 0, 30)
        ws.set_column(1, 8, 13)
        excel_banner(wb, ws, [30] + [13] * 8, f"Monthly attendance - {label(month)} - {item.recipient_name}")
        kpis = [("Employees", totals["employees"]), ("Working days", totals["work_days"]), ("Days uploaded", totals["working_days"]),
                ("Average attendance %", totals["attendance_pct"] if totals["attendance_pct"] is not None else "-"),
                ("Absences (days)", totals["absent"]), ("Leave (days)", totals["leave"] + totals["half_day"]), ("On duty", totals["od"]),
                ("Work from home", totals["wfh"]), ("Late arrivals", totals["late"]), ("Missing punches", totals["missing_punch"]),
                ("Full attendance (people)", len(blocks.get("perfect") or []))]
        for i, (k, v) in enumerate(kpis, start=2):
            ws.write(i, 0, k, bold)
            ws.write(i, 1, v, pct_fmt[band(totals["attendance_pct"])] if k.startswith("Average") else big)
        r = 3 + len(kpis)
        if blocks.get("concerns"):
            ws.write(r, 0, "Needs your attention", head)
            for i, x in enumerate(blocks["concerns"], start=r + 1):
                ws.write(i, 0, "- " + x)
            r += 2 + len(blocks["concerns"])
        if view == "hr" and blocks.get("checklist"):
            ws.write(r, 0, "Before payroll", head)
            ws.write(r, 1, "People", head)
            ws.write(r, 2, "In all", head)
            for i, g in enumerate(blocks["checklist"], start=r + 1):
                ws.write(i, 0, g["title"], cell)
                ws.write(i, 1, len(g["rows"]), num if g["rows"] else zero)
                ws.write(i, 2, g["total"], num if g["total"] else zero)
            r += 2 + len(blocks["checklist"])
        ws.write(r, 0, "Daily trend (attendance %)", head)
        ws.write(r, 1, "Attendance %", head)
        for i, t in enumerate(totals["trend"], start=r + 1):
            ws.write(i, 0, date.fromisoformat(t["date"]).strftime(settings.app.date_format + " (%a)"), cell)
            ws.write(i, 1, "" if t["attendance_pct"] is None else t["attendance_pct"], pct_fmt[band(t["attendance_pct"])])
        if totals["trend"]:
            chart = wb.add_chart({"type": "column"})
            chart.add_series({"name": "Attendance %", "categories": ["Summary", r + 1, 0, r + len(totals["trend"]), 0],
                              "values": ["Summary", r + 1, 1, r + len(totals["trend"]), 1], "fill": {"color": "#16A34A"}, "gap": 40})
            chart.set_title({"name": "Daily attendance %", "name_font": {"size": 11, "color": "#14213D"}})
            chart.set_legend({"none": True})
            chart.set_y_axis({"min": 0, "max": 100, "major_gridlines": {"visible": True, "line": {"color": "#E6E8EF"}}})
            chart.set_size({"width": 620, "height": 260})
            ws.insert_chart(r, 3, chart)
        r = r + 2 + len(totals["trend"])
        ws.write(r, 0, "Next month planning", head)
        for i, n in enumerate(blocks["planning"], start=r + 1):
            ws.write(i, 0, "- " + n)
        r += 2 + len(blocks["planning"])
        if blocks.get("perfect"):
            ws.write(r, 0, "Full attendance - worth a word of thanks", head)
            for i, x in enumerate(blocks["perfect"], start=r + 1):
                ws.write(i, 0, f"{x['name']} ({x['code']})", cell)
            r += 2 + len(blocks["perfect"])
        ws.write(r, 0, "Attendance is a workforce-availability indicator, not a measure of productivity.", note)

    def teams():
        ws = wb.add_worksheet("Teams")
        cols = [("Rank", "rank", 6), ("HOD's team", "name", 30), ("People", "employees", 8), ("Attendance %", "attendance_pct", 12),
                (f"{label(previous_month_of(month))} %", "before", 11), ("Change (pts)", "change", 11), ("Absences", "absent", 10),
                ("Leave", "leave", 8), ("Late", "late", 8), ("Missing punch", "missing_punch", 10), ("Need attention", "attention", 10)]
        excel_banner(wb, ws, [w for _, _, w in cols], f"Teams at a glance - {label(month)}", "By HOD's team, best attendance first")
        for j, (h, _, w) in enumerate(cols):
            ws.write(3, j, h, head)
            ws.set_column(j, j, w)
        for i, g in enumerate(groups, start=4):
            for j, (_, k, _) in enumerate(cols):
                v = g.get(k)
                if k == "change":
                    v, f = chg(v)
                else:
                    f = pct_fmt[band(v)] if k in ("attendance_pct", "before") and v is not None else bold if k == "name" else num
                ws.write(i, j, "" if v is None else v, f)
        last = 3 + len(groups)
        if groups:
            chart = wb.add_chart({"type": "bar"})
            chart.add_series({"name": "Attendance %", "categories": ["Teams", 4, 1, last, 1], "values": ["Teams", 4, 3, last, 3],
                              "fill": {"color": "#14213D"}, "gap": 50, "data_labels": {"value": True, "num_format": "0.0"}})
            chart.set_title({"name": "Attendance % by team", "name_font": {"size": 11, "color": "#14213D"}})
            chart.set_legend({"none": True})
            chart.set_x_axis({"min": 0, "max": 100, "major_gridlines": {"visible": True, "line": {"color": "#E6E8EF"}}})
            chart.set_y_axis({"reverse": True})
            chart.set_size({"width": 620, "height": max(260, 24 * len(groups) + 80)})
            ws.insert_chart(last + 2, 1, chart)
        ws.freeze_panes(4, 2)

    def needs_attention():
        attention = sorted([p for p in people if p["reason"]], key=lambda p: (-p["absent"], -p["missing_punch"], -p["late"], p["name"]))
        wsa = wb.add_worksheet("Needs attention")
        acols = [("Code", "code", 11), ("Name", "name", 26)] + team_col + [
            ("Absent", "absent", 8), ("Late", "late", 7), ("Missing punch", "missing_punch", 9),
            ("Attendance %", "attendance_pct", 11), ("Change vs last month (pts)", "change", 12), ("Pattern", "reason", 30),
            ("Action required (manager)", "action", 52)]
        excel_banner(wb, wsa, [w for _, _, w in acols], f"Recurring patterns - action required - {label(month)}",
                     f"{ATTENTION['absent']}+ absences, {ATTENTION['late']}+ late arrivals or {ATTENTION['missing_punch']}+ missing punches")
        hr = 3
        for j, (h, _, w) in enumerate(acols):
            wsa.write(hr, j, h, head)
            wsa.set_column(j, j, w)
        for i, p in enumerate(attention, start=hr + 1):
            for j, (_, k, _) in enumerate(acols):
                v = monthly_action(p)[0] if k == "action" else p.get(k)
                if k == "change":
                    v, fmt = chg(v)
                else:
                    fmt = act if k == "action" else pct_fmt[band(v)] if k == "attendance_pct" else wrap if k == "reason" else cell
                wsa.write(i, j, "" if v is None else v, fmt)
        if not attention:
            wsa.write(hr + 1, 0, "No recurring absence, late-arrival or missing-punch patterns this month.", note)
        wsa.freeze_panes(hr + 1, 2)

    def weeks_sheet():
        ws = wb.add_worksheet("Weeks")
        wk = (ins or {}).get("weeks") or []
        cols = [("Week", 10), ("Dates", 18), ("Days", 7), ("Attendance %", 12), ("Absent", 9), ("Late", 8), ("Missing punch", 10)]
        excel_banner(wb, ws, [w for _, w in cols], f"Week by week - {label(month)}")
        for j, (h, w) in enumerate(cols):
            ws.write(3, j, h, head)
            ws.set_column(j, j, w)
        ok = [w for w in wk if w["attendance_pct"] is not None]
        lo = min(ok, key=lambda w: w["attendance_pct"]) if len(ok) > 1 else None
        hi = max(ok, key=lambda w: w["attendance_pct"]) if len(ok) > 1 else None
        for i, w in enumerate(wk, start=4):
            ws.write(i, 0, w["week"] + (" (weakest)" if w is lo else " (best)" if w is hi else ""), bold)
            ws.write(i, 1, w["range"], cell)
            ws.write(i, 2, w["days"], num)
            ws.write(i, 3, "" if w["attendance_pct"] is None else w["attendance_pct"], pct_fmt[band(w["attendance_pct"])])
            for j, k in ((4, "absent"), (5, "late"), (6, "missing_punch")):
                ws.write(i, j, w[k], num if w[k] else zero)
        ws.set_column(0, 0, 18)
        if wk:
            last = 3 + len(wk)
            c1 = wb.add_chart({"type": "column"})
            c1.add_series({"name": "Attendance %", "categories": ["Weeks", 4, 1, last, 1], "values": ["Weeks", 4, 3, last, 3],
                           "fill": {"color": "#16A34A"}, "gap": 60, "data_labels": {"value": True, "num_format": "0.0"}})
            c1.set_title({"name": "Attendance % by week", "name_font": {"size": 11, "color": "#14213D"}})
            c1.set_legend({"none": True})
            c1.set_y_axis({"min": 0, "max": 100, "major_gridlines": {"visible": True, "line": {"color": "#E6E8EF"}}})
            c1.set_size({"width": 480, "height": 260})
            ws.insert_chart(last + 2, 0, c1)
            c2 = wb.add_chart({"type": "column"})
            for col, name, colour in ((4, "Absent", "#DC2626"), (5, "Late", "#D97706"), (6, "Missing punch", "#7C3AED")):
                c2.add_series({"name": name, "categories": ["Weeks", 4, 1, last, 1], "values": ["Weeks", 4, col, last, col],
                               "fill": {"color": colour}, "gap": 60})
            c2.set_title({"name": "Absences, late arrivals and missing punches by week", "name_font": {"size": 11, "color": "#14213D"}})
            c2.set_legend({"position": "bottom"})
            c2.set_size({"width": 480, "height": 260})
            ws.insert_chart(last + 2, 4, c2)

    def routing_problems():
        held = blocks.get("held") or []
        if not held:
            return
        ws = wb.add_worksheet("Routing problems")
        cols = [("Code", 12), ("Name", 28), ("Problem", 34), ("What to do", 60)]
        excel_banner(wb, ws, [w for _, w in cols], f"Employees whose report has no HOD to go to - {label(month)}")
        for j, (h, w) in enumerate(cols):
            ws.write(3, j, h, head)
            ws.set_column(j, j, w)
        for i, h in enumerate(held, start=4):
            ws.write(i, 0, h["code"], cell)
            ws.write(i, 1, h["name"], bold)
            ws.write(i, 2, routing_issue_text(h["issue"]), wrap)
            ws.write(i, 3, "Fix the HOD email in Employee mapping so their manager gets their report.", act)

    def employees_sheet():
        ws2 = wb.add_worksheet("Employees")
        cols = [("Code", "code", 11), ("Name", "name", 26)] + team_col + [("Needs attention", "reason", 26),
                ("Days", "days", 6), ("Present", "present", 8), ("Absent", "absent", 8), ("Leave", "leave", 7),
                ("Half day", "half_day", 8), ("WFH", "wfh", 6), ("OD", "od", 5), ("Late", "late", 6), ("Missing punch", "missing_punch", 9),
                ("Week off", "week_off", 8), ("Attendance %", "attendance_pct", 11), ("Change vs last month (pts)", "change", 12),
                ("Avg arrival", "avg_in_time", 10)]
        for j, (h, _, w) in enumerate(cols):
            ws2.write(0, j, h, head)
            ws2.set_column(j, j, w)
        ordered = sorted(people, key=lambda p: (not p["reason"], p["department"], p["name"]))
        for i, p in enumerate(ordered, start=1):
            for j, (_, k, _) in enumerate(cols):
                v = p.get(k)
                if k == "avg_in_time":
                    v = analysis.t12(v)
                if k == "change":
                    v, fmt = chg(v)
                else:
                    fmt = pct_fmt[band(v)] if k == "attendance_pct" else flag if p["reason"] else cell
                ws2.write(i, j, "" if v is None else v, fmt)
        ws2.autofilter(0, 0, len(ordered), len(cols) - 1)
        ws2.freeze_panes(1, 2)

    def calendar_sheet():
        ws3 = wb.add_worksheet("Calendar")
        ws3.write(0, 0, "Code", head)
        ws3.write(0, 1, "Name", head)
        ws3.set_column(0, 0, 10)
        ws3.set_column(1, 1, 26)
        ws3.set_row(0, 30)
        for j, d in enumerate(days, start=2):
            ws3.write(0, j, d.strftime("%d") + chr(10) + d.strftime("%a")[:2], head)
            ws3.set_column(j, j, 4.3)
        ws3.write(0, len(days) + 2, "Att. %", head)
        ws3.set_column(len(days) + 2, len(days) + 2, 8)
        for i, p in enumerate(sorted(people, key=lambda p: p["name"]), start=1):
            ws3.write(i, 0, p["code"], cell)
            ws3.write(i, 1, p["name"], flag if p["reason"] else cell)
            for j, d in enumerate(days, start=2):
                c = p["codes"].get(d.isoformat(), "")
                ws3.write(i, j, "" if c == "P" else c, day_fmt.get(c, day_fmt[""]))
            ws3.write(i, len(days) + 2, "" if p["attendance_pct"] is None else p["attendance_pct"], pct_fmt[band(p["attendance_pct"])])
        ws3.write(len(people) + 2, 1, "Blank green = present · MP missing punch · OD on duty · WFH · HD half day · L leave · A absent · WO week off · - not tracked", note)
        ws3.freeze_panes(1, 2)

    def insights():
        if ins:
            _insights_sheet(wb, ins, month, head, cell, bold, wrap, note, pct_fmt, band)

    order = {"hod": [summary, insights, needs_attention, weeks_sheet, employees_sheet, calendar_sheet],
             "director": [summary, teams, insights, needs_attention, weeks_sheet, employees_sheet, calendar_sheet],
             "hr": [summary, teams, needs_attention, routing_problems, weeks_sheet, insights, employees_sheet, calendar_sheet]}[view]
    for sheet in order:
        sheet()
    wb.close()
    return buf.getvalue()


# ---------------------------------------------------------------------------- month-end dashboard
# Colour and label of each day code (same palette as the daily dashboard).
DAY_CODES = [  # code, label, colour
    ("P", "Present", "#16a34a"), ("OD", "On duty", "#0d9488"), ("WFH", "Work from home", "#4f46e5"), ("HD", "Half day", "#f59e0b"),
    ("L", "Leave", "#64748b"), ("A", "Absent", "#dc2626"), ("MP", "Missing punch", "#7c3aed"), ("WO", "Week off", "#cbd5e1"), ("HO", "Holiday", "#fcd34d"),
    ("-", "Not tracked", "#e2e8f0"),
]
DAY_COLOR = {c: col for c, _, col in DAY_CODES}
_FLAG_LETTER = {"LATE": "L", "LEFT_EARLY": "E", "SHORT_HOURS": "S", "PERMISSION": "P", "PERMISSION_PENDING": "Q"}


def previous_month_of(month: str) -> str:
    return (month_bounds(month)[0] - timedelta(days=1)).strftime("%Y-%m")


def monthly_action(p: dict) -> tuple[str, str]:
    """(action for the manager, icon) for one person with a recurring pattern."""
    if p["absent"] >= ATTENTION["absent"]:
        return "Discuss the repeated absences; make sure leave is applied in Pocket HRMS", "chat"
    if p["missing_punch"] >= ATTENTION["missing_punch"]:
        return "Regularise the missing punches before payroll", "check-square"
    if p["late"] >= ATTENTION["late"]:
        return "Counsel on punctuality and agree a correction plan", "user-cog"
    return "Review", "chat"


def _minutes(hhmm: str | None) -> int | None:
    if not hhmm:
        return None
    h, m = hhmm.split(":")[:2]
    return int(h) * 60 + int(m)


def dashboard_html(settings: Settings, item: MailItem, month: str, days: list[date], people: list[dict], totals: dict,
                   blocks: dict, by_code: dict, prev: dict | None, prev_people: dict | None, prev_trend: list[dict] | None,
                   ins: dict, rules) -> bytes:
    """The month-end dashboard: a self-contained, tabbed app (Overview, Trends, People, Calendar, Action plan) that
    recomputes every figure in the browser for any period the viewer picks. No network access, no external files."""
    from daily.branding import logo_data_uri

    view = blocks.get("view", "hod")
    company = view in ("director", "hr")
    rows = []
    for p in sorted(people, key=lambda p: p["name"]):
        per = by_code.get(p["code"].upper(), {})
        d = []
        for day in days:
            x = per.get(day)
            if not x:
                d.append(None)
                continue
            d.append([STATUS_CODE.get(x["status"], "?"), _minutes(x["in_time"]), _minutes(x["out_time"]),
                      round(x["work_hours"] * 60) if x["work_hours"] is not None else None, x["late_minutes"] or 0,
                      x["early_minutes"] or 0, x.get("leave_type") or "", "".join(_FLAG_LETTER.get(f, "") for f in x["flags"])])
        b = (prev_people or {}).get(p["code"].upper())
        rows.append({"code": p["code"], "name": p["name"], "d": d, **({"hod": p.get("hod") or NO_HOD} if company else {}),
                     "prev": {"pct": b["attendance_pct"], "absent": b["absent"], "late": b["late"], "mp": b["missing_punch"],
                              "leave": b["leave"] + b["half_day"]} if b else None})
    first = month_bounds(month)[0]
    payload = {
        "month": month, "monthLong": first.strftime("%B %Y"), "prevLabel": label(previous_month_of(month)),
        "days": [d.isoformat() for d in days], "people": rows,
        "prevTrend": [t["attendance_pct"] for t in (prev_trend or [])],
        "prevTotals": {k: prev.get(k) for k in ("attendance_pct", "absent", "late", "missing_punch", "leave", "half_day", "wfh", "od")}
                      if prev else None,
        "rules": {"lateAfter": _minutes(rules.flexi_until or rules.late_after), "minHours": rules.min_work_hours,
                  "singlePunchPresent": rules.single_punch_counts_present, "target": ins["target"]},
        "thresholds": {"absent": ATTENTION["absent"], "late": ATTENTION["late"], "mp": ATTENTION["missing_punch"]},
        "codes": {c: {"label": lbl, "color": col} for c, lbl, col in DAY_CODES},
        "storeKey": f"apis-month-{month}-{item.recipient_key}",
        "planning": blocks["planning"],
        "view": view, "recipient": item.recipient_name,
        "prevTeams": {g["name"]: g["before"] for g in blocks.get("groups") or [] if g.get("before") is not None},
    }
    data_json = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    data_json = data_json.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
    is_director = company
    return _env.get_template("monthly_dashboard.html").render(company=company,
        title=f"Monthly Attendance - {label(month)} - {item.recipient_name}", logo=logo_data_uri(), data_json=data_json,
        recipient="HR team" if view == "hr" else item.recipient_name, month_long=first.strftime("%B %Y"),
        heading="Monthly Company Attendance Report" if is_director else "Monthly Team Attendance Report",
        subtitle=("The company" if is_director else "Your team") + " – month-end insights, trends & action plan",
        who="the company" if is_director else "your team", t=totals, n=len(people), ins=ins, has_prev=prev is not None,
        prev_month=label(previous_month_of(month)), working_days=len(days),
    ).encode("utf-8")


def _previous(session: Session, settings: Settings, month: str, codes: set[str], rules
              ) -> tuple[dict | None, int | None, dict | None, list[dict] | None]:
    """The same people in the previous month: (totals, people needing attention, per person, daily trend).
    All None when that month has no uploaded days (or none of these people)."""
    pm = previous_month_of(month)
    pdays, pby = _rows_by_code(session, pm)
    if not pdays:
        return None, None, None, None
    end = month_bounds(pm)[1]
    route_of = {r.code.upper(): r for r in routing.routes(session, end)}
    ppl = {c: _person(c, next(iter(pby[c].values()))["name"], route_of.get(c), pby[c], rules) for c in codes if pby.get(c)}
    if not ppl:
        return None, None, None, None
    totals = _scope_totals(list(ppl.values()), pdays, pby, rules)
    return totals, sum(1 for p in ppl.values() if p["reason"]), ppl, totals["trend"]


def _insights_sheet(wb, ins: dict, month: str, head, cell, bold, wrap, note, pct_fmt, band) -> None:
    """Key takeaways and the pattern tables behind them (weekday, week, streaks, Mon/Fri, movers, perfect, leave)."""
    ws = wb.add_worksheet("Insights")
    ws.set_column(0, 0, 34)
    ws.set_column(1, 6, 14)
    excel_banner(wb, ws, [34] + [14] * 6, f"Key takeaways - {label(month)}")
    kind = {"good": wb.add_format({"bg_color": "#E8F6EC", "font_color": "#15803D", "bold": True, "border": 1, "border_color": "#E6E8EF", "align": "center"}),
            "warn": wb.add_format({"bg_color": "#FFF3E0", "font_color": "#B45309", "bold": True, "border": 1, "border_color": "#E6E8EF", "align": "center"}),
            "bad": wb.add_format({"bg_color": "#FDECEC", "font_color": "#B91C1C", "bold": True, "border": 1, "border_color": "#E6E8EF", "align": "center"}),
            "info": wb.add_format({"bg_color": "#E0F2FE", "font_color": "#0369A1", "bold": True, "border": 1, "border_color": "#E6E8EF", "align": "center"})}
    r = 3
    for t in ins["takeaways"]:
        ws.write(r, 0, {"good": "Good", "warn": "Watch", "bad": "Act", "info": "Note"}[t["kind"]], kind[t["kind"]])
        ws.merge_range(r, 1, r, 6, t["text"], wrap)
        ws.set_row(r, 32)
        r += 1

    def table(title, cols, rows):
        nonlocal r
        r += 1
        ws.write(r, 0, title, bold)
        r += 1
        for j, (h, _) in enumerate(cols):
            ws.write(r, j, h, head)
        r += 1
        if not rows:
            ws.write(r, 0, "None this month.", note)
            r += 1
        for row in rows:
            for j, (_, k) in enumerate(cols):
                v = row.get(k) if isinstance(k, str) else k(row)
                ws.write(r, j, "" if v is None else v, pct_fmt[band(v)] if k == "attendance_pct" else cell)
            r += 1

    table("By weekday", [("Weekday", "day"), ("Days", "days"), ("Attendance %", "attendance_pct"), ("Absences", "absent"), ("Late", "late"),
                         ("Missing punch", "missing_punch")], ins["weekday"])
    table("Week by week", [("Week", lambda w: f"{w['week']} ({w['range']})"), ("Days", "days"), ("Attendance %", "attendance_pct"),
                           ("Absences", "absent"), ("Late", "late"), ("Missing punch", "missing_punch")], ins["weeks"])
    table("Absent 3+ report days in a row", [("Employee", lambda x: f"{x['name']} ({x['code']})"), ("Days in a row", "days"),
                                            ("From", lambda x: x["from"].strftime("%d-%b")), ("To", lambda x: x["to"].strftime("%d-%b"))], ins["streaks"])
    table("Absences clustered on Mondays / Fridays", [("Employee", lambda x: f"{x['name']} ({x['code']})"), ("Mon / Fri", "mon_fri"),
                                                     ("All absences", "absent")], ins["monday_friday"])
    table("Slipped 5+ pts vs last month", [("Employee", lambda x: f"{x['name']} ({x['code']})"), ("Last month %", "before"),
                                          ("This month %", "now"), ("Change (pts)", "change")], ins["declined"])
    table("Improved 5+ pts vs last month", [("Employee", lambda x: f"{x['name']} ({x['code']})"), ("Last month %", "before"),
                                           ("This month %", "now"), ("Change (pts)", "change")], ins["improved"])
    table("Perfect attendance (recognise)", [("Employee", lambda x: f"{x['name']} ({x['code']})"), ("Tracked days", "tracked"),
                                            ("Attendance %", "attendance_pct")], ins["perfect"])
    table("Leave by type", [("Leave type", "type"), ("Days", "days")], ins["leave_mix"])


# ---------------------------------------------------------------------------- listing
def summaries(session: Session) -> list[dict]:
    out = []
    for m in session.scalars(select(MonthlySummary).order_by(MonthlySummary.month.desc())):
        out.append({"month": m.month, "label": label(m.month), "days": m.days, "employees": m.employees,
                    "attendance_pct": m.attendance_pct, "status": m.status, "archive": bool(m.archive_path),
                    "generated_at": m.generated_at.isoformat(), "generated_by": m.generated_by,
                    "cleaned_at": m.cleaned_at.isoformat() if m.cleaned_at else None})
    return out


def items(session: Session, month: str) -> list[MailItem]:
    end = month_bounds(month)[1]
    return list(session.scalars(select(MailItem).where(MailItem.report_date == end, MailItem.recipient_key.like(f"{PREFIX}%"),
                                                       MailItem.status != mail.SUPERSEDED).order_by(MailItem.id)))


# ---------------------------------------------------------------------------- cleanup
def cleanable_before(today: date, keep_months: int) -> str:
    """Months strictly before this YYYY-MM may be cleaned (keep_months=2: keep the current and previous month)."""
    y, m = today.year, today.month - (keep_months - 1)
    while m <= 0:
        y, m = y - 1, m + 12
    return f"{y:04d}-{m:02d}"


def check_cleanup(session: Session, settings: Settings, month: str, today: date | None = None) -> list[str]:
    """Reasons why `month` may NOT be cleaned yet (empty list = safe)."""
    problems = []
    limit = cleanable_before(today or jobs.yesterday_ist() + timedelta(days=1), settings.jobs.keep_months)
    if month >= limit:
        problems.append(f"{label(month)} is within the last {settings.jobs.keep_months} month(s) that are kept.")
    s = session.get(MonthlySummary, month)
    if s is None:
        problems.append(f"No monthly report has been generated for {label(month)}.")
        return problems
    if s.status == "CLEANED":
        problems.append(f"{label(month)} was already cleaned.")
    if not s.archive_path or not Path(s.archive_path).is_file():
        problems.append("The monthly archive file is missing.")
    elif sha256_bytes(Path(s.archive_path).read_bytes()) != s.archive_sha256:
        problems.append("The monthly archive file has changed since it was written.")
    b = jobs.last_good_backup(session)
    if b is None or b.finished_at is None or b.finished_at < s.generated_at:
        problems.append("No successful database backup since the monthly archive was written - run the backup first.")
    return problems


def cleanup(settings: Settings, engine, month: str, confirm: bool = False, trigger: str = "MANUAL", actor: str = "admin",
            today: date | None = None) -> dict:
    """Remove the month's daily employee rows and stored upload files - only when every check passes.
    Without `confirm` it only reports what would be removed."""
    with jobs.job_lock(settings, "cleanup"):
        with session_scope(engine) as s:
            problems = check_cleanup(s, settings, month, today)
            days = _days(s, month)
            rows = s.scalar(select(EmployeeDay.id).where(EmployeeDay.upload_id.in_(list(days.values()) or [-1])).limit(1))
            preview = {"month": month, "days": len(days), "has_rows": rows is not None}
            if problems or not confirm:
                return {"status": "BLOCKED" if problems else "PREVIEW", "problems": problems, **preview}
            run_id = jobs.start_job(s, "CLEANUP", month, trigger, actor).id
        with session_scope(engine) as s:
            uploads = list(days.values())
            deleted = s.execute(delete(EmployeeDay).where(EmployeeDay.upload_id.in_(uploads))).rowcount
            removed_files = 0
            for d in days:
                folder = settings.storage.area("uploads") / d.isoformat()
                if folder.is_dir():
                    shutil.rmtree(folder)
                    removed_files += 1
            for up in s.scalars(select(DayUpload).where(DayUpload.upload_id.in_(uploads))):
                up.stored_path = up.permission_path = up.bizom_path = None
            summary = s.get(MonthlySummary, month)
            summary.status, summary.cleaned_at = "CLEANED", now_utc()
            result = {"status": jobs.SUCCESS, "month": month, "rows_deleted": deleted, "upload_folders_removed": removed_files}
            jobs.finish_job(s, s.get(JobRun, run_id), jobs.SUCCESS, result)
        return {"run_id": run_id, **result}
