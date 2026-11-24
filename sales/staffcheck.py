"""Staff list problems for HR, each with its proof from the uploaded days:

* possibly left - an Active person who USED to appear in Bizom's attendance file but has not on any of the last LEFT_AFTER
  working days (Sundays / holidays are not counted), with no leave recorded: their absences are probably not real absences;
* never in Bizom - Active on the staff list but not in Bizom's file on a single uploaded day since joining (often a senior
  or office role that does not use Bizom); they are counted absent every day until HR removes them or they start marking;
* joining date looks wrong - Bizom shows them working before the date of joining on the staff list.
"""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from database.models.sales import SalesDayUpload, SalesEmployee, SalesEmployeeDay

LEFT_AFTER = 15                 # working days in a row not in Bizom's file


def issues(session: Session, upto: date, codes: set[str] | None = None) -> dict:
    ups = [u for u in session.scalars(select(SalesDayUpload).where(SalesDayUpload.is_current.is_(True), SalesDayUpload.report_date <= upto)
                                      .order_by(SalesDayUpload.report_date))]
    working = [u for u in ups if not json.loads(u.summary or "{}").get("off_day")]
    staff = {e.code: e for e in session.scalars(select(SalesEmployee).where(SalesEmployee.status == "ACTIVE"))}
    if codes is not None:
        staff = {c: e for c, e in staff.items() if c in codes}
    in_file: dict[str, list[date]] = defaultdict(list)             # days the person was in Bizom's own file
    leave_days: dict[str, list[date]] = defaultdict(list)
    for d, code, bs, st in session.execute(
            select(SalesDayUpload.report_date, SalesEmployeeDay.code, SalesEmployeeDay.bizom_status, SalesEmployeeDay.status)
            .join(SalesEmployeeDay, SalesEmployeeDay.upload_id == SalesDayUpload.upload_id)
            .where(SalesDayUpload.is_current.is_(True), SalesDayUpload.report_date <= upto, SalesEmployeeDay.code.in_(list(staff)))):
        if bs is not None:
            in_file[code].append(d)
        if st == "LEAVE":
            leave_days[code].append(d)
    left, never, doj = [], [], []
    recent = [u.report_date for u in working[-LEFT_AFTER:]]
    for code, e in sorted(staff.items(), key=lambda kv: kv[1].name):
        seen = sorted(in_file.get(code, []))
        if len(recent) == LEFT_AFTER and (not e.date_of_joining or e.date_of_joining <= recent[0]) \
                and not any(d >= recent[0] for d in seen) and not any(d >= recent[0] for d in leave_days.get(code, [])):
            row = {"code": code, "name": e.name, "designation": e.designation or "", "manager": e.manager_name or "", "hod": e.hod_name or ""}
            since = max(e.date_of_joining, working[0].report_date) if e.date_of_joining else working[0].report_date
            if seen:
                left.append({**row, "last_seen": seen[-1].isoformat(),
                             "proof": f"No attendance record on any of the last {LEFT_AFTER} working days "
                                      f"({recent[0]:%d-%b} to {recent[-1]:%d-%b}), no leave recorded; last seen on {seen[-1]:%d-%b-%Y}."})
            else:
                n = sum(1 for u in working if u.report_date >= since)
                never.append({**row, "last_seen": None,
                              "proof": f"No attendance record on any of {n} working days from {since:%d-%b-%Y} to {recent[-1]:%d-%b-%Y}."})
        if e.date_of_joining and seen and seen[0] < e.date_of_joining:
            early = [d for d in seen if d < e.date_of_joining]
            doj.append({"code": code, "name": e.name, "manager": e.manager_name or "", "hod": e.hod_name or "",
                        "doj": e.date_of_joining.isoformat(), "first_seen": early[0].isoformat(),
                        "proof": f"Marked attendance on {len(early)} day(s) before the joining date {e.date_of_joining:%d-%b-%Y}, "
                                 f"first on {early[0]:%d-%b-%Y}."})
    return {"upto": upto.isoformat(), "working_days_checked": len(recent), "possibly_left": left, "never_in_bizom": never, "doj_wrong": doj}


NEVER_AFTER = 20                # working days since joining with no Bizom row at all = does not use Bizom


def never_users(session: Session, day: date) -> set[str]:
    """Active staff who have never been in Bizom's attendance file on any uploaded day (any date), although at least
    NEVER_AFTER working days have been uploaded since they joined (up to `day`)."""
    seen = {c for (c,) in session.execute(select(SalesEmployeeDay.code).join(SalesDayUpload, SalesDayUpload.upload_id == SalesEmployeeDay.upload_id)
                                         .where(SalesDayUpload.is_current.is_(True), SalesEmployeeDay.bizom_status.is_not(None)).distinct())}
    working = [d for d, s in session.execute(select(SalesDayUpload.report_date, SalesDayUpload.summary).where(
        SalesDayUpload.is_current.is_(True), SalesDayUpload.report_date < day)) if not json.loads(s or "{}").get("off_day")]
    out = set()
    for e in session.scalars(select(SalesEmployee).where(SalesEmployee.status == "ACTIVE")):
        if e.code in seen:
            continue
        since = e.date_of_joining or date.min
        if sum(1 for d in working if d >= since) >= NEVER_AFTER:
            out.add(e.code)
    return out


def reconcile(session: Session) -> dict:
    """After a bulk load: staff who turned out never to use Bizom are taken out of the absence counts of every day
    (only the rows the app added for them - never Bizom's own rows); each day's totals are counted again."""
    from collections import Counter

    from sales import analysis, report
    last = session.scalar(select(SalesDayUpload.report_date).where(SalesDayUpload.is_current.is_(True)).order_by(SalesDayUpload.report_date.desc()))
    if last is None:
        return {"people": 0, "rows_removed": 0}
    codes = never_users(session, last)
    removed = 0
    for up in session.scalars(select(SalesDayUpload).where(SalesDayUpload.is_current.is_(True))):
        rows = list(session.scalars(select(SalesEmployeeDay).where(SalesEmployeeDay.upload_id == up.upload_id)))
        drop = [r for r in rows if r.code in codes and r.bizom_status is None and r.status in ("ABSENT", "WEEK_OFF")]
        if not drop:
            continue
        for r in drop:
            session.delete(r)
        keep = [r for r in rows if r not in drop]
        s = json.loads(up.summary)
        c = Counter(r.status for r in keep)
        s["counts"] = {k: c.get(k, 0) for k in analysis.STATUS_LABEL}
        s["attendance_pct"], s["people"] = report.pct_of(keep), len(keep)
        s["not_bizom_users"] = s.get("not_bizom_users", 0) + len(drop)
        up.summary, up.people = json.dumps(s), len(keep)
        removed += len(drop)
    session.flush()
    return {"people": len(codes), "rows_removed": removed}


def last_known(session: Session, before: date | None = None) -> dict[str, tuple]:
    """code -> (designation, zone, manager) from each person's most recent row in Bizom's own file (before `before`)."""
    from sqlalchemy import func
    q = (select(SalesEmployeeDay.code, SalesEmployeeDay.designation, SalesEmployeeDay.zone, SalesEmployeeDay.manager_name,
                func.max(SalesDayUpload.report_date))
         .join(SalesDayUpload, SalesDayUpload.upload_id == SalesEmployeeDay.upload_id)
         .where(SalesDayUpload.is_current.is_(True), SalesEmployeeDay.bizom_status.is_not(None)))
    if before is not None:
        q = q.where(SalesDayUpload.report_date < before)
    return {code: (des, zone, mgr) for code, des, zone, mgr, _ in session.execute(q.group_by(SalesEmployeeDay.code))}


def fill_details(session: Session) -> int:
    """Fill a blank designation / zone / manager on rows the app added (absent, week off, holiday) from the person's
    last day in Bizom. Bizom's own rows are never touched."""
    known = last_known(session)
    n = 0
    for r in session.scalars(select(SalesEmployeeDay).where(SalesEmployeeDay.bizom_status.is_(None))):
        k = known.get(r.code)
        if not k:
            continue
        changed = False
        for attr, val in zip(("designation", "zone", "manager_name"), k):
            if val and not getattr(r, attr):
                setattr(r, attr, val)
                changed = True
        n += changed
    session.flush()
    return n
