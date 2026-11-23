"""Count a field sales day and work out the warning signs ("needs checking").

Status (Bizom decides present / late / halfday from the attendance time):
  PRESENT   Bizom "present" (marked by 10:30)
  LATE      Bizom "late" (10:31 - 13:59) - counts as present, flagged late
  HALF_DAY  Bizom "halfday" (14:00 or later) - counts as half a day
  LEAVE     Bizom "absent" with a leave reason (Privilege / Sick / Casual ...)
  WEEK_OFF  Bizom "absent" with "Weekly Off" - left out of attendance %
  ABSENT    Bizom "absent" with no reason, OR active on the staff list but not in the attendance file ("not marked")

Attendance % = (present + late + half of half days) / (everyone - week off).

Warning signs are not proof of anything: each one is something for the manager to check, shown with its evidence.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field

from database.models.sales import SalesEmployee
from sales.bizom import AttendanceRow, BizomFile, CallSummary, EodRow, minutes_of, norm_name
from sales.config import SalesRules

PRESENT, LATE, HALF_DAY, LEAVE, WEEK_OFF, ABSENT = "PRESENT", "LATE", "HALF_DAY", "LEAVE", "WEEK_OFF", "ABSENT"
WORKING = (PRESENT, LATE, HALF_DAY)
STATUS_LABEL = {PRESENT: "Present", LATE: "Late", HALF_DAY: "Half day", LEAVE: "Leave", WEEK_OFF: "Week off", ABSENT: "Absent"}

# code: (label, level, why it matters)
WARNINGS: dict[str, tuple[str, str, str]] = {
    "NO_ACTIVITY": ("Marked attendance, no market activity", "high", "No transaction or call all day after marking attendance."),
    "VERY_SHORT_MARKET": ("Under 1 hour in market", "high", "Marked attendance but spent very little time in the market."),
    "SHORT_MARKET": ("Under 4 hours in market", "medium", "Less than half a working day in the market."),
    "LATE_START": ("Started work 4+ hours after marking", "medium", "Attendance marked early, first activity much later."),
    "SHORT_CALLS": ("Many very short visits", "high", "Several outlet visits under a minute - possible visits logged without a real visit."),
    "FAR_CALLS": ("Visit logged away from the outlet", "high", "Call location far from the outlet's location."),
    "FAST_MOVES": ("Impossible travel between visits", "high", "Two visits too far apart for the time between them."),
    "HIGH_KM": ("Very high KM travelled", "medium", "Unusually long distance for one day - worth checking."),
    "ZERO_KM": ("0 KM but market activity", "medium", "Location tracking off or not working while working in market."),
    "FAR_ATTENDANCE": ("Attendance marked away from the expected spot", "medium", "Attendance location differs from the expected place."),
    "NO_PHOTO": ("No attendance photo", "medium", "Attendance marked without the selfie."),
    "SHORT_DAY": ("Short day (attendance to day-end)", "medium", "Day ended less than 4 hours after marking attendance."),
    "DAY_NOT_CLOSED": ("Day not closed", "low", "Did not end the day in Bizom; it closed automatically at 23:59."),
    "BEAT_JUMP": ("Visits outside the planned beat", "low", "Several outlets visited outside today's route."),
    "CALLS_AFTER_HOURS": ("Visits logged late in the evening", "low", "Outlet visits logged after working hours."),
    "ODD_HOUR": ("Attendance marked at an odd hour", "medium", "Attendance marked very early in the morning or late in the evening."),
}
LEVEL_ORDER = {"high": 0, "medium": 1, "low": 2}


@dataclass
class PersonDay:
    code: str
    name: str
    designation: str | None
    zone: str | None
    manager_name: str | None
    zonal_name: str | None
    hod_name: str | None
    in_master: bool
    status: str
    bizom_status: str | None = None
    leave_type: str | None = None
    attendance_time: str | None = None
    first_activity: str | None = None
    last_activity: str | None = None
    market_minutes: int | None = None
    km: float | None = None
    eod_time: str | None = None
    attendance_variance_m: float | None = None
    photo: bool | None = None
    calls: CallSummary | None = None
    flags: list[str] = field(default_factory=list)
    att_location: tuple[float, float] | None = None      # where attendance was marked
    eod_location: tuple[float, float] | None = None      # where the day was ended
    photo_url: str | None = None
    present_type: str | None = None                       # HQ / EX-HQ work that day (Bizom)


def _match(rx: list[str], code: str) -> bool:
    return any(re.search(p, code, re.IGNORECASE) for p in rx)


def is_promoter(code: str, designation: str | None, rules: SalesRules) -> bool:
    return _match(rules.promoter_codes, code) or "promoter" in (designation or "").lower()


def _status(r: AttendanceRow) -> tuple[str, str | None]:
    s = r.status
    if s == "present":
        return PRESENT, None
    if s == "late":
        return LATE, None
    if s == "halfday":
        return HALF_DAY, None
    if s == "absent":
        lv = (r.leave or "").strip()
        if lv.lower().startswith("weekly off") or lv.lower() in ("wo", "week off"):
            return WEEK_OFF, None
        if lv:
            return LEAVE, lv.replace("Causal", "Casual")
        return ABSENT, None
    return ABSENT, None


def _eod_lookup(eod: list[EodRow]) -> tuple[dict, dict, dict]:
    """EMP_CODE first (Employee_ID in newer exports); the name only for rows without a code, and only when unique."""
    codes = Counter(e.code for e in eod if e.marked and e.code)
    by_code = {e.code: e for e in eod if e.marked and e.code and codes[e.code] == 1}
    no_code = [e for e in eod if e.marked and not e.code]
    by_name_time = {(norm_name(e.name), e.attendance_time): e for e in no_code}
    names = Counter(norm_name(e.name) for e in no_code)
    by_name = {norm_name(e.name): e for e in no_code if names[norm_name(e.name)] == 1}
    return by_code, by_name_time, by_name


def warnings(p: PersonDay, rules: SalesRules, have_eod: bool, have_calls: bool) -> list[str]:
    if p.status not in WORKING:
        return []
    f = []
    c = p.calls
    active = bool(p.first_activity) or bool(c and c.calls)
    supervisor = (p.designation or "").strip().upper() in {d.strip().upper() for d in rules.supervisor_designations}
    a, first = minutes_of(p.attendance_time), minutes_of(p.first_activity)
    if not supervisor:                          # market-activity checks: field roles only
        if not active:
            f.append("NO_ACTIVITY")
        elif p.market_minutes is not None:
            if p.market_minutes < rules.very_short_market_minutes:
                f.append("VERY_SHORT_MARKET")
            elif p.market_minutes < rules.short_market_minutes:
                f.append("SHORT_MARKET")
        if a is not None and first is not None and first - a >= rules.late_start_minutes:
            f.append("LATE_START")
    if p.km is not None:
        if p.km > rules.high_km:
            f.append("HIGH_KM")
        elif p.km == 0 and active:
            f.append("ZERO_KM")
    if a is not None and (a < minutes_of(rules.odd_hour_before) or a >= minutes_of(rules.odd_hour_after)):
        f.append("ODD_HOUR")
    if p.attendance_variance_m is not None and p.attendance_variance_m > rules.attendance_far_m:
        f.append("FAR_ATTENDANCE")
    if p.photo is False:
        f.append("NO_PHOTO")
    if have_eod and p.eod_time:
        if p.eod_time == "23:59":
            f.append("DAY_NOT_CLOSED")
        elif a is not None and minutes_of(p.eod_time) - a < rules.short_day_minutes:
            f.append("SHORT_DAY")
    if have_calls and c and c.calls:
        if c.short >= rules.short_calls_min and c.short * 2 >= c.calls:
            f.append("SHORT_CALLS")
        if c.far:
            f.append("FAR_CALLS")
        if c.fast_moves:
            f.append("FAST_MOVES")
        if c.beat_jump >= rules.beat_jump_min:
            f.append("BEAT_JUMP")
        if c.outside_hours:
            f.append("CALLS_AFTER_HOURS")
    return sorted((x for x in f if x not in rules.disabled_signs), key=lambda x: (LEVEL_ORDER[WARNINGS[x][1]], x))


@dataclass
class DayResult:
    people: list[PersonDay]
    summary: dict


def analyse(att: BizomFile, eod: BizomFile | None, calls: BizomFile | None, staff: list[SalesEmployee], rules: SalesRules,
            not_bizom_users: set[str] = frozenset(), person_holidays: dict[str, str] | None = None,
            company_holiday: str | None = None) -> DayResult:
    """not_bizom_users: staff who have never been in Bizom's file since joining (sales.staffcheck) - not counted absent.
    person_holidays: code -> holiday name from HR's yearly list for that person's confirmed state (sales.holiday_states)."""
    person_holidays = person_holidays or {}
    master = {e.code: e for e in staff}
    by_code, by_name_time, by_name = _eod_lookup(eod.eod) if eod else ({}, {}, {})
    people: list[PersonDay] = []
    seen: set[str] = set()
    excluded = Counter()
    left_but_marked: list[str] = []
    for r in att.attendance:
        if r.code in seen:
            continue
        seen.add(r.code)
        m = master.get(r.code)
        if _match(rules.exclude_codes, r.code):
            excluded["excluded code"] += 1
            continue
        if not rules.include_promoters and is_promoter(r.code, (m.designation if m else None) or r.designation, rules):
            excluded["promoter"] += 1
            continue
        if m is not None and m.status == "LEFT":
            left_but_marked.append(f"{r.name} ({r.code})")
        st, leave = _status(r)
        e = by_code.get(r.code) or by_name_time.get((norm_name(r.name), r.attendance_time)) or by_name.get(norm_name(r.name))
        p = PersonDay(code=r.code, name=(m.name if m else r.name), designation=(m.designation if m and m.designation else r.designation),
                      zone=(m.zone if m and m.zone else r.zone), manager_name=(m.manager_name if m and m.manager_name else r.manager),
                      zonal_name=m.zonal_name if m else None, hod_name=m.hod_name if m else None, in_master=m is not None,
                      status=st, bizom_status=r.status or None, leave_type=leave, attendance_time=r.attendance_time,
                      first_activity=r.first_activity, last_activity=r.last_activity, market_minutes=r.market_minutes, km=r.km,
                      eod_time=e.eod_time if e else (r.end_time if st in WORKING else None),
                      attendance_variance_m=r.variance_m, photo=r.photo,
                      calls=(calls.calls.get(r.code) if calls else None),
                      att_location=(e.location if e and e.location else r.location),
                      eod_location=e.eod_location if e and st in WORKING else None,
                      photo_url=r.photo_url or (e.photo_url if e else None), present_type=r.present_type)
        people.append(p)
    not_marked = not_yet = not_users = 0
    off_day, unconfirmed, marked, expected = None, False, 0, 0
    if rules.not_marked_is_absent:
        day = att.report_date
        missing = []
        for code, m in master.items():
            if code in seen or m.status != "ACTIVE" or _match(rules.exclude_codes, code):
                continue
            if not rules.include_promoters and is_promoter(code, m.designation, rules):
                continue
            if m.date_of_joining and m.date_of_joining > day:
                not_yet += 1                          # had not joined yet on this day: not absent
                continue
            if code in not_bizom_users:
                not_users += 1                        # never marks attendance in Bizom: on HR's list, not counted absent
                continue
            missing.append(m)
        regional = [m for m in missing if m.code in person_holidays]          # holiday on their state's list: not due
        missing = [m for m in missing if m.code not in person_holidays]
        for m in regional:
            people.append(PersonDay(code=m.code, name=m.name, designation=m.designation, zone=m.zone, manager_name=m.manager_name,
                                    zonal_name=m.zonal_name, hod_name=m.hod_name, in_master=True, status=WEEK_OFF,
                                    leave_type=f"Holiday – {person_holidays[m.code]}"[:40]))
        marked = sum(1 for p in people if p.status in WORKING)
        expected = marked + len(missing)
        off_day, unconfirmed = off_day_of(day, marked, expected, rules, company_holiday)
        for m in missing:
            people.append(PersonDay(code=m.code, name=m.name, designation=m.designation, zone=m.zone, manager_name=m.manager_name,
                                    zonal_name=m.zonal_name, hod_name=m.hod_name, in_master=True,
                                    status=WEEK_OFF if off_day else ABSENT, leave_type=off_leave(off_day)))
            not_marked += 1
    for p in people:
        p.flags = warnings(p, rules, eod is not None, calls is not None)
    res = DayResult(people, summarise(people, att, eod, calls, not_marked, excluded, left_but_marked))
    res.summary["off_day"], res.summary["not_yet_joined"], res.summary["not_bizom_users"] = off_day, not_yet, not_users
    res.summary["state_holidays"] = dict(Counter(person_holidays[p.code] for p in res.people
                                              if p.code in person_holidays and p.status == WEEK_OFF and (p.leave_type or "").startswith("Holiday")))
    res.summary["off_day_unconfirmed"] = bool(rules.not_marked_is_absent and unconfirmed)
    res.summary["marked"], res.summary["expected"] = (marked, expected) if rules.not_marked_is_absent else (None, None)
    return res


def off_leave(off_day: str | None) -> str | None:
    return None if not off_day else "Sunday" if off_day == "Sunday" else "Holiday"


def off_day_of(day, marked: int, expected: int, rules: SalesRules, company_holiday: str | None = None) -> tuple[str | None, bool]:
    """(off-day label or None, still to be confirmed by HR). HR's calendar wins; a Sunday is off; a day when fewer than
    `off_day_below` of the staff marked attendance LOOKS like a holiday - treated as one, but the emails wait for HR."""
    iso = day.isoformat()
    if iso in rules.working_days:
        return None, False
    if iso in rules.holidays:
        return f"Holiday – {rules.holidays[iso]}" if rules.holidays[iso] else "Holiday", False
    if company_holiday:                                     # on every page of HR's yearly holiday list
        return f"Holiday – {company_holiday}", False
    if rules.sunday_off and day.weekday() == 6:
        return "Sunday", False
    if expected and marked < rules.off_day_below * expected:
        return f"Holiday? (only {marked} of {expected} marked attendance)", True
    return None, False


def pct(people: list[PersonDay]) -> float | None:
    c = Counter(p.status for p in people)
    due = len(people) - c[WEEK_OFF]
    return round(100 * (c[PRESENT] + c[LATE] + 0.5 * c[HALF_DAY]) / due, 1) if due else None


def summarise(people: list[PersonDay], att: BizomFile, eod: BizomFile | None, calls: BizomFile | None, not_marked: int,
              excluded: Counter, left_but_marked: list[str]) -> dict:
    c = Counter(p.status for p in people)
    flags = Counter(f for p in people for f in p.flags)
    working = [p for p in people if p.status in WORKING]
    times = [minutes_of(p.attendance_time) for p in working if p.attendance_time]
    mkt = [p.market_minutes for p in working if p.market_minutes is not None]
    eod_not_marked = sum(1 for e in (eod.eod if eod else []) if not e.marked)
    return {
        "date": att.report_date.isoformat(), "people": len(people), "counts": {k: c.get(k, 0) for k in STATUS_LABEL},
        "not_marked": not_marked, "attendance_pct": pct(people),
        "avg_attendance_time": (f"{(sum(times) // len(times)) // 60:02d}:{(sum(times) // len(times)) % 60:02d}" if times else None),
        "avg_market_minutes": round(sum(mkt) / len(mkt)) if mkt else None,
        "warnings": {k: flags.get(k, 0) for k in WARNINGS if flags.get(k)},
        "people_flagged": sum(1 for p in people if p.flags),
        "people_high": sum(1 for p in people if any(WARNINGS[f][1] == "high" for f in p.flags)),
        "calls": ({"people": sum(1 for p in people if p.calls), "calls": sum(p.calls.calls for p in people if p.calls),
                   "productive": sum(p.calls.productive for p in people if p.calls),
                   "order_value": round(sum(p.calls.order_value for p in people if p.calls), 2)} if calls else None),
        "files": {"attendance": True, "eod": eod is not None, "calls": calls is not None},
        "data": {"not_in_staff_list": sorted(f"{p.name} ({p.code})" for p in people if not p.in_master),
                 "left_but_marked": left_but_marked, "excluded": dict(excluded), "skipped_rows": att.skipped,
                 "eod_not_marked": eod_not_marked,
                 "calls_people_not_in_file": (sorted(set(calls.calls) - {p.code for p in people}) if calls else [])},
    }
