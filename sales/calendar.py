"""Field Sales holiday calendar (kept by HR). Bizom never marks Sundays / holidays as off, so on such days the people who
did not mark attendance are counted as off, not absent. A day that only LOOKS like a holiday (few people marked) is
treated as one but its emails wait until HR confirms it here - the app never decides a holiday on its own."""

from __future__ import annotations

import json
from collections import Counter
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from database.models.sales import SalesDayUpload, SalesEmployeeDay, SalesMailItem
from sales import analysis
from sales.config import get_rules, save_rules

SYNTH_LEAVE = (None, "Sunday", "Holiday")


def _not_marked(session: Session, up: SalesDayUpload) -> list[SalesEmployeeDay]:
    """Rows the app added for staff missing from Bizom's file (never Bizom's own rows)."""
    return [r for r in session.scalars(select(SalesEmployeeDay).where(SalesEmployeeDay.upload_id == up.upload_id))
            if r.bizom_status is None and r.in_master and r.status in ("ABSENT", "WEEK_OFF")
            and (r.leave_type in SYNTH_LEAVE or (r.leave_type or "").startswith("Holiday"))]


def apply(session: Session, day: date, actor: str) -> dict | None:
    """Re-apply the calendar to an uploaded day: only the not-marked people change (absent <-> off); counts are redone and
    waiting emails are prepared again. Returns the new day summary (None if the day is not uploaded)."""
    from sales import mail, report, service
    up = service.current_upload(session, day)
    if up is None:
        return None
    from sales import holiday_states
    rules = get_rules(session)
    rows = list(session.scalars(select(SalesEmployeeDay).where(SalesEmployeeDay.upload_id == up.upload_id)))
    synth = _not_marked(session, up)
    hol = holiday_states.person_holidays(session, day)
    due = [r for r in synth if r.code not in hol]
    marked = sum(1 for r in rows if r.status in analysis.WORKING)
    from daily import holiday_list
    off, unconfirmed = analysis.off_day_of(day, marked, marked + len(due), rules, holiday_list.company_holiday(session, day))
    for r in synth:
        if r.code in hol:
            r.status, r.leave_type = "WEEK_OFF", f"Holiday – {hol[r.code]}"[:40]
        else:
            r.status, r.leave_type = ("WEEK_OFF" if off else "ABSENT"), analysis.off_leave(off)
    session.flush()
    s = json.loads(up.summary)
    c = Counter(r.status for r in rows)
    s["counts"] = {k: c.get(k, 0) for k in analysis.STATUS_LABEL}
    s["attendance_pct"] = report.pct_of(rows)
    s["off_day"], s["off_day_unconfirmed"], s["marked"], s["expected"] = off, unconfirmed, marked, marked + len(due)
    s["state_holidays"] = dict(Counter(hol[r.code] for r in synth if r.code in hol))
    if s.get("verify"):
        s["verify"]["note"] = f"Holiday calendar applied by {actor}; {len(synth)} not-marked people re-counted."
    up.summary = json.dumps(s)
    items = [i for i in session.scalars(select(SalesMailItem).where(SalesMailItem.report_date == day,
                                                                     SalesMailItem.recipient_key.not_like("MONTHLY:%")))]
    if any(i.status in mail.REPLACEABLE for i in items):
        for i in items:
            if i.status in mail.REPLACEABLE:
                i.status, i.note = mail.SUPERSEDED, "Prepared again after the holiday calendar changed."
        mail.plan(session, up)
    session.flush()
    return s


def state(session: Session) -> dict:
    rules = get_rules(session)
    waiting = []
    for up in session.scalars(select(SalesDayUpload).where(SalesDayUpload.is_current.is_(True)).order_by(SalesDayUpload.report_date)):
        s = json.loads(up.summary or "{}")
        if s.get("off_day_unconfirmed"):
            waiting.append({"date": up.report_date.isoformat(), "weekday": f"{up.report_date:%A}", "marked": s.get("marked"),
                            "expected": s.get("expected")})
    return {"holidays": [{"date": d, "name": n} for d, n in sorted(rules.holidays.items())], "working_days": sorted(rules.working_days),
            "waiting": waiting, "rule": f"Sundays are off; a day when fewer than {round(rules.off_day_below * 100)}% marked "
                                        "attendance waits for HR to confirm it as a holiday or a working day."}


def decide(session: Session, day: date, kind: str, name: str, actor: str) -> dict | None:
    """kind: holiday | working | clear."""
    if kind not in ("holiday", "working", "clear"):
        raise ValueError("kind must be holiday, working or clear.")
    rules = get_rules(session)
    iso = day.isoformat()
    rules.holidays.pop(iso, None)
    rules.working_days = [d for d in rules.working_days if d != iso]
    if kind == "holiday":
        rules.holidays[iso] = (name or "").strip()[:60]
    elif kind == "working":
        rules.working_days.append(iso)
    save_rules(session, rules, actor)
    return apply(session, day, actor)


def apply_year(session: Session, year: int, actor: str) -> dict:
    """Re-apply the calendar (HR's yearly list + each person's state + HR's own decisions) to every uploaded day of a year.
    Only the not-marked people can change; Bizom's own rows never do."""
    days = [d for (d,) in session.execute(select(SalesDayUpload.report_date).where(
        SalesDayUpload.is_current.is_(True), SalesDayUpload.report_date >= date(year, 1, 1), SalesDayUpload.report_date <= date(year, 12, 31)))]
    changed = 0
    for d in sorted(days):
        before = session.scalar(select(SalesDayUpload.summary).where(SalesDayUpload.report_date == d, SalesDayUpload.is_current.is_(True)))
        after = apply(session, d, actor)
        if after and json.loads(before or "{}").get("counts") != after.get("counts"):
            changed += 1
    return {"days": len(days), "days_changed": changed}
