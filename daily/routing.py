"""Who receives whose attendance (Build brief: APIS Daily Attendance Auto-Mailer, section 3).

Rules, per employee in the employee master (EMP_CODE is the only join key, never the name):

1. Detail recipient = the Sub split ID (team lead) email; if blank, the HOD email; if there is no HOD,
   the Director (Director Office staff).
2. Department summary = the HOD email: every HOD gets a summary of everyone under them.
3. A routing issue such as HOD_EMAIL_CONFLICT puts the employee in the HR exception queue - never
   sent to an assumed person. So do invalid / ambiguous addresses.
4. Attendance codes that are not in the employee master go to the HR exception report.
5. The Reporting Manager name is informational only.

One email per recipient per day: a team lead who is also an HOD gets ONE combined email.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from core.config import EmailSettings
from daily import employees as emp
from daily.settings_store import valid_email
from database.models.daily import Employee, MailRecipient

DIRECTOR, HR = "DIRECTOR", "HR"
HOLD_ISSUES = ("HOD_EMAIL_CONFLICT", "HOLD")
PLACEHOLDERS = {"DIRECTOR_EMAIL_TBC": DIRECTOR, "HR_EXCEPTION_QUEUE": HR}


@dataclass
class Route:
    code: str
    name: str
    department: str
    hod: str
    team: str
    manager: str
    detail_to: str                  # recipient email (lower-case), DIRECTOR or HR
    rule: str
    summary_to: str | None          # HOD email, or None
    issue: str | None = None        # why it is in the HR queue


def route_employee(e: Employee) -> Route:
    hod_mails = list(dict.fromkeys(m.lower() for m in emp.emails_in(e.hod_email)))
    sub_raw = (e.team_lead_email or "").strip()
    sub = [m.lower() for m in emp.emails_in(sub_raw)]
    held = e.routing_issue and any(h in e.routing_issue.upper() for h in HOLD_ISSUES)
    base = dict(code=e.code, name=e.name, department=e.department or "", hod=e.hod_name or "", team=emp.team_of(e.team_lead_email),
                manager=e.reporting_manager or "")
    summary = hod_mails[0] if len(hod_mails) == 1 and not held else None
    if held:
        return Route(**base, detail_to=HR, rule="Held for HR", summary_to=None, issue=e.routing_issue)
    if len(sub) == 1:
        return Route(**base, detail_to=sub[0], rule="Sub split ID", summary_to=summary)
    if sub_raw:
        return Route(**base, detail_to=HR, rule="Held for HR", summary_to=summary,
                     issue="INVALID_SUB_SPLIT_EMAIL" if not sub else "MULTIPLE_SUB_SPLIT_EMAILS")
    if len(hod_mails) == 1:
        return Route(**base, detail_to=hod_mails[0], rule="No Sub split ID: HOD", summary_to=summary)
    if len(hod_mails) > 1:
        return Route(**base, detail_to=HR, rule="Held for HR", summary_to=None, issue="HOD_EMAIL_CONFLICT (two HOD emails)")
    if not e.hod_name:
        return Route(**base, detail_to=DIRECTOR, rule="No HOD: Director", summary_to=None)
    return Route(**base, detail_to=HR, rule="Held for HR", summary_to=None, issue="NO_HOD_EMAIL")


def active_on(e: Employee, day: date | None) -> bool:
    if e.status != emp.LEFT:
        return True
    return day is not None and e.exit_date is not None and e.exit_date >= day


def routes(session: Session, day: date | None = None) -> list[Route]:
    return [route_employee(e) for e in emp.list_all(session) if active_on(e, day)]


# ---------------------------------------------------------------------------- recipients
@dataclass
class Recipient:
    key: str                                   # email, DIRECTOR or HR
    name: str
    role: str                                  # Team lead | HOD | HOD + Team lead | Director | HR
    to: list[str]
    cc: list[str] = field(default_factory=list)
    team: list[Route] = field(default_factory=list)       # detail
    summary: list[Route] = field(default_factory=list)    # HOD scope
    company: bool = False                                 # Director: company summary by HOD
    status: str = "OK"                                    # OK | HELD | DISABLED
    note: str | None = None


def switches(session: Session) -> dict[str, MailRecipient]:
    return {r.email.lower(): r for r in session.scalars(select(MailRecipient))}


def _display_name(key: str, team: list[Route], hod_names: dict[str, str], overrides: dict[str, MailRecipient]) -> str:
    if key in overrides and overrides[key].name:
        return overrides[key].name
    if key in hod_names:
        return hod_names[key]
    mgr = Counter(r.manager for r in team if r.manager).most_common(1)
    if mgr:
        return mgr[0][0].title() if mgr[0][0].isupper() else mgr[0][0]
    return key.split("@")[0]


def recipients(session: Session, cfg: EmailSettings, day: date | None = None, all_routes: list[Route] | None = None) -> list[Recipient]:
    """The planned recipients (before attendance): one per email address, plus Director and HR."""
    rs = all_routes if all_routes is not None else routes(session, day)
    team: dict[str, list[Route]] = defaultdict(list)
    summary: dict[str, list[Route]] = defaultdict(list)
    hod_names: dict[str, Counter] = defaultdict(Counter)
    for r in rs:
        team[r.detail_to].append(r)
        if r.summary_to:
            summary[r.summary_to].append(r)
            if r.hod:
                hod_names[r.summary_to][r.hod] += 1
    names = {k: c.most_common(1)[0][0] for k, c in hod_names.items()}
    overrides = switches(session)
    out: list[Recipient] = []
    for key in sorted((set(team) | set(summary)) - {DIRECTOR, HR}, key=lambda k: (-len(team.get(k, [])), k)):
        t, s = team.get(key, []), summary.get(key, [])
        role = "HOD + Team lead" if t and s else "HOD" if s else "Team lead"
        rec = Recipient(key, _display_name(key, t, names, overrides), role, [key], team=t, summary=s)
        if not cfg.team_emails:
            rec.team = []
        if not cfg.hod_summary:
            rec.summary = []
        if cfg.hod_cc_on_team and rec.team:
            rec.cc = sorted({r.summary_to for r in rec.team if r.summary_to and r.summary_to != key})
        if cfg.hr_cc_on_hod_summary and rec.summary:
            rec.cc = sorted(set(rec.cc) | {m.lower() for m in cfg.hr_emails})
        if not rec.team and not rec.summary:
            rec.status, rec.note = "DISABLED", "Switched off in Settings (routing switches)."
        sw = overrides.get(key)
        if sw and (not sw.active or (day and sw.effective_from and day < sw.effective_from)
                   or (day and sw.effective_to and day > sw.effective_to)):
            rec.status, rec.note = "DISABLED", "Switched off for this recipient."
        out.append(rec)
    director = Recipient(DIRECTOR, cfg.director_name or "Director", "Director", [m.lower() for m in cfg.director_emails],
                         team=team.get(DIRECTOR, []), company=True)
    if not cfg.director_report:
        director.status, director.note = "DISABLED", "Director report switched off in Settings."
    out.append(director)
    hr = Recipient(HR, "HR Attendance", "HR", [m.lower() for m in cfg.hr_emails], team=team.get(HR, []))
    if not cfg.hr_exceptions:
        hr.status, hr.note = "DISABLED", "HR exception report switched off in Settings."
    out.append(hr)
    for rec in out:
        if rec.status != "OK":
            continue
        bad = [a for a in rec.to + rec.cc if not valid_email(a)]
        if not rec.to:
            rec.status, rec.note = "HELD", ("Director email not set (Settings -> Email)." if rec.key == DIRECTOR else
                                            "HR mailbox not set (Settings -> Email)." if rec.key == HR else "No address.")
        elif bad:
            rec.status, rec.note = "HELD", f"Invalid address: {', '.join(bad)}"
    return out


def overview(session: Session, cfg: EmailSettings, day: date | None = None) -> dict:
    """Routing check (no attendance needed): who gets what, coverage totals and the HR queue."""
    rs = routes(session, day)
    recs = recipients(session, cfg, day, rs)
    held = [r for r in rs if r.detail_to == HR]
    return {
        "employees": len(rs),
        "detail_total": sum(Counter(r.detail_to for r in rs).values()),
        "routed_to_people": sum(1 for r in rs if r.detail_to not in (DIRECTOR, HR)),
        "routed_to_director": sum(1 for r in rs if r.detail_to == DIRECTOR),
        "unique": len({r.code for r in rs}) == len(rs),
        "recipients": [{"key": r.key, "name": r.name, "role": r.role, "to": r.to, "cc": r.cc, "team": len(r.team),
                        "summary": len(r.summary), "status": r.status, "note": r.note} for r in recs],
        "held": [{"code": r.code, "name": r.name, "department": r.department, "hod": r.hod, "issue": r.issue} for r in held],
        "rules": Counter(r.rule for r in rs),
    }


def compare_with_coverage(session: Session, coverage: list[dict]) -> dict:
    """Compare the app's routing with the Employee_Coverage sheet of HR's routing workbook."""
    mine = {r.code: r for r in routes(session)}
    diffs = []
    for row in coverage:
        code = emp.norm_code(row.get("code", ""))
        if not code:
            continue
        expected = (row.get("detail") or "").strip()
        expected = PLACEHOLDERS.get(expected.upper(), expected.lower())
        expected_sum = (row.get("summary") or "").strip()
        expected_sum = None if expected_sum.upper() in PLACEHOLDERS or not expected_sum else expected_sum.lower()
        r = mine.get(code)
        if r is None:
            diffs.append({"code": code, "issue": "In the coverage sheet but not an active employee here"})
        elif r.detail_to != expected:
            diffs.append({"code": code, "issue": f"Detail recipient: sheet {expected}, app {r.detail_to}"})
        elif expected_sum and r.summary_to != expected_sum:
            diffs.append({"code": code, "issue": f"HOD summary: sheet {expected_sum}, app {r.summary_to}"})
    return {"checked": len(coverage), "differences": len(diffs), "examples": diffs[:20]}


# ---------------------------------------------------------------------------- routing workbook
CONFIG_MAP = {  # (report type, recipient role contains) -> EmailSettings switch
    ("direct report attendance", "direct manager"): "team_emails",
    ("direct report attendance", "director"): "director_report",
    ("direct report attendance", "hod"): "hod_cc_on_team",
    ("hod summary", "hod"): "hod_summary",
    ("hod summary", "hr"): "hr_cc_on_hod_summary",
    ("hr exception report", "hr"): "hr_exceptions",
}
ON_WORDS = {"ACTIVE", "ENABLED", "ON", "YES", "Y", "TRUE"}
OFF_WORDS = {"DISABLED", "INACTIVE", "OFF", "NO", "N", "FALSE"}


def apply_workbook(session: Session, settings, extras: dict, actor: str) -> dict:
    """Apply the Email_Routing_Config and Recipient_Master sheets and check Employee_Coverage."""
    from daily.settings_store import get_email_settings, save_email_settings

    out: dict = {}
    if extras.get("config"):
        cfg = get_email_settings(session, settings)
        values = cfg.model_dump()
        applied, disabled = {}, []
        for row in extras["config"]:
            rtype = emp._clean(row.get("report type")).lower()
            role = emp._clean(row.get("recipient role")).lower()
            status = emp._clean(row.get("active status")).upper()
            for (t, r), key in CONFIG_MAP.items():
                if rtype == t and role.startswith(r):
                    if status in ON_WORDS:
                        applied[key] = True
                    elif status in OFF_WORDS:
                        applied[key] = False
                        disabled.append(f"{row.get('report type')} -> {row.get('recipient role')}")
                    break
            sender = emp._clean(row.get("sender email")).lower()
            reply = emp._clean(row.get("reply to")).lower()
            if sender and valid_email(sender):
                applied["sender"] = sender
            if reply and valid_email(reply):
                applied["reply_to"] = reply
        if applied:
            save_email_settings(session, type(cfg).model_validate({**values, **applied}), actor)
        out["config"] = {"applied": applied, "disabled": disabled}
    if extras.get("recipients"):
        existing = switches(session)
        count = 0
        for row in extras["recipients"]:
            email = emp._clean(row.get("report to email")).lower()
            if not valid_email(email):
                continue
            status = emp._clean(row.get("active status")).upper()
            rec = existing.get(email) or MailRecipient(email=email, active=True)
            rec.active = status not in OFF_WORDS
            rec.effective_from = emp.parse_date(row.get("effective from")) if emp._clean(row.get("effective from")) else None
            rec.effective_to = emp.parse_date(row.get("effective to")) if emp._clean(row.get("effective to")) else None
            rec.updated_by = actor
            session.add(rec)
            count += 1
        session.flush()
        out["recipients"] = {"imported": count, "switched_off": sum(1 for r in switches(session).values() if not r.active)}
    if extras.get("coverage"):
        out["coverage"] = compare_with_coverage(session, extras["coverage"])
    return out


def set_recipient(session: Session, email: str, active: bool | None, name: str | None, actor: str) -> MailRecipient:
    email = email.strip().lower()
    if not valid_email(email):
        raise ValueError("Not a valid email address.")
    rec = switches(session).get(email) or MailRecipient(email=email, active=True)
    if active is not None:
        rec.active = active
    if name is not None:
        rec.name = name.strip() or None
    rec.updated_by = actor
    session.add(rec)
    session.flush()
    return rec
