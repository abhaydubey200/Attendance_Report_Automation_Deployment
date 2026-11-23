"""Field Sales patterns over each person's own recent days - the 'why it matters' behind a single day.

Every pattern is a plain COUNT over the uploaded days, and lists the exact dates (and times / hours) it is based on, so an
HOD can check each one in Bizom. Nothing here is a guess or a model score:

* a pattern is reported only on a day the person adds to it (e.g. absent again), so the same line is not repeated daily;
* only working days count: week offs, leave and days without an upload are skipped, never treated as absent;
* the thresholds were chosen on 6 months of real data (May-Nov 2026) so that each pattern is rare (see PATTERN_RULES).
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from daily.analysis import t12
from database.models.sales import SalesDayUpload, SalesEmployeeDay

DUE = ("PRESENT", "LATE", "HALF_DAY", "ABSENT")          # days the person was expected to work
WORKED = ("PRESENT", "LATE", "HALF_DAY")
WEEKDAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")

# code: (label, level) - level as in the rest of Module 2 (high / medium / low)
PATTERNS = {
    "ABSENT_REPEAT": ("Absent often without leave", "high"),
    "ABSENT_WEEKDAY": ("Absent on the same weekday", "high"),
    "ABSENT_NEXT_TO_OFF": ("Absent next to week offs / leave", "medium"),
    "LATE_REPEAT": ("Late often", "medium"),
    "SHORT_MARKET_REPEAT": ("Short time in market, again", "medium"),
    "NO_ACTIVITY_REPEAT": ("Marked attendance with no market activity, again", "high"),
    "DAY_NOT_CLOSED_REPEAT": ("Day not closed, again", "low"),
    "LOCATION_REPEAT": ("Location signs on several days", "high"),
    "ATTENDANCE_DROP": ("Attendance has dropped", "high"),
}


@dataclass
class Rules:
    # Tuned on 6 months of real data (May-Nov 2026, ~450 field staff a day) so each pattern is rare and clear-cut.
    window_days: int = 30            # look back this many uploaded working days
    absent_min: int = 6              # ABSENT_REPEAT: absent without leave on at least this many of them (20%)
    weekday_lookback: int = 5        # ABSENT_WEEKDAY: the last N times this weekday was a working day
    weekday_min: int = 4             # ... absent on at least this many of them
    weekday_ratio: float = 2.0       # ... and at least twice as often as on their other working days
    next_to_off_min: int = 4         # ABSENT_NEXT_TO_OFF: absences the day before / after a week off or leave
    late_lookback: int = 10          # LATE_REPEAT: of the last N working days ...
    late_min: int = 5                # ... late on at least this many
    market_lookback: int = 10
    market_minutes: int = 240        # SHORT_MARKET_REPEAT: under 4 h in market ...
    market_min: int = 5              # ... on at least this many of the last N days worked (field roles only)
    no_activity_min: int = 5         # NO_ACTIVITY_REPEAT: of the last 10 days worked
    not_closed_min: int = 7          # DAY_NOT_CLOSED_REPEAT: of the last 10 days worked
    location_min: int = 3            # LOCATION_REPEAT: days with a high-level location sign in the last 10 days worked
    drop_recent: int = 20            # ATTENDANCE_DROP: attendance % of the last N working days ...
    drop_before: int = 40            # ... vs the N working days before them
    drop_points: float = 25.0        # ... down at least this many points
    drop_recent_max: float = 70.0    # ... and now below this %
    quiet_days: int = 7              # the same pattern for the same person is shown at most once in this many days


@dataclass
class Day:
    d: date
    status: str
    leave: str | None
    att: str | None
    market: int | None
    flags: set[str] = field(default_factory=set)
    geo_high: list[str] = field(default_factory=list)


def _fmt(d: date) -> str:
    return f"{d.day}-{d:%b}"


def _dates(ds: list[date], n: int = 8) -> str:
    s = ", ".join(_fmt(x) for x in sorted(ds)[-n:])
    return s if len(ds) <= n else f"{s} (and {len(ds) - n} earlier)"


def history(session: Session, upto: date, codes: set[str] | None, days_back: int = 120) -> dict[str, list[Day]]:
    """Each person's uploaded days (current uploads only), oldest first, up to `upto`."""
    from sales.geo import GEO
    from sales.trust import JUDGMENT
    high_geo = {k for k, v in GEO.items() if v[1] == "high" and k not in JUDGMENT}   # measured location facts only
    q = (select(SalesDayUpload.report_date, SalesEmployeeDay.code, SalesEmployeeDay.status, SalesEmployeeDay.leave_type,
                SalesEmployeeDay.attendance_time, SalesEmployeeDay.market_minutes, SalesEmployeeDay.flags, SalesEmployeeDay.geo_flags)
         .join(SalesDayUpload, SalesDayUpload.upload_id == SalesEmployeeDay.upload_id)
         .where(SalesDayUpload.is_current.is_(True), SalesDayUpload.report_date <= upto,
                SalesDayUpload.report_date > upto - timedelta(days=days_back)))
    if codes is not None:
        q = q.where(SalesEmployeeDay.code.in_(codes))
    out: dict[str, list[Day]] = defaultdict(list)
    for d, code, st, lv, att, mk, fl, gf in session.execute(q.order_by(SalesDayUpload.report_date)):
        out[code].append(Day(d, st, lv, att, mk, set((fl or "").split(",")) - {""},
                             [g for g in (gf or "").split(",") if g in high_geo]))
    return out


def person(days: list[Day], today: date, rules: Rules = Rules(), field_role: bool = True) -> list[dict]:
    """Patterns this person adds to on `today` (their last uploaded day must be `today`). Each:
    {code, label, level, text (one line with the proof), dates}."""
    if not days or days[-1].d != today:
        return []
    t = days[-1]
    due = [x for x in days if x.status in DUE]
    worked = [x for x in days if x.status in WORKED]
    out: list[dict] = []

    def add(code: str, text: str, ds: list[date]) -> None:
        out.append({"code": code, "label": PATTERNS[code][0], "level": PATTERNS[code][1], "text": text,
                    "dates": [x.isoformat() for x in sorted(ds)]})

    if t.status == "ABSENT":
        win = due[-rules.window_days:]
        ab = [x.d for x in win if x.status == "ABSENT"]
        if len(ab) >= rules.absent_min:
            add("ABSENT_REPEAT", f"Absent without leave on {len(ab)} of the last {len(win)} working days: {_dates(ab)}.", ab)
        same = [x for x in due if x.d.weekday() == today.weekday()][-rules.weekday_lookback:]
        ab_wd = [x.d for x in same if x.status == "ABSENT"]
        others = [x for x in win if x.d.weekday() != today.weekday()]
        other_rate = sum(1 for x in others if x.status == "ABSENT") / len(others) if others else 0.0
        if (len(same) >= rules.weekday_lookback and len(ab_wd) >= rules.weekday_min
                and len(ab_wd) / len(same) >= rules.weekday_ratio * other_rate):
            add("ABSENT_WEEKDAY", f"Absent on {len(ab_wd)} of the last {len(same)} {WEEKDAYS[today.weekday()]}s: {_dates(ab_wd)}.", ab_wd)
        # absences right before / after a week off or leave (by calendar day, both days uploaded)
        by_d = {x.d: x for x in days}
        nxt = []
        for x in win:
            if x.status != "ABSENT":
                continue
            for n in (x.d - timedelta(days=1), x.d + timedelta(days=1)):
                y = by_d.get(n)
                if y is not None and y.status in ("WEEK_OFF", "LEAVE"):
                    nxt.append(x.d)
                    break
        if len(nxt) >= rules.next_to_off_min and today in nxt:
            add("ABSENT_NEXT_TO_OFF", f"Absent next to a week off or leave on {len(nxt)} days: {_dates(nxt)}.", nxt)

    if t.status == "LATE":
        last = due[-rules.late_lookback:]
        late = [x for x in last if x.status == "LATE"]
        if len(late) >= rules.late_min:
            add("LATE_REPEAT", f"Late on {len(late)} of the last {len(last)} working days: "
                               + ", ".join(f"{_fmt(x.d)} {t12(x.att) or ''}".strip() for x in late[-6:]) + ".", [x.d for x in late])

    if t.status in WORKED and field_role:
        last = worked[-rules.market_lookback:]
        if t.market is not None and t.market < rules.market_minutes:
            short = [x for x in last if x.market is not None and x.market < rules.market_minutes]
            if len(short) >= rules.market_min:
                add("SHORT_MARKET_REPEAT", f"Under {rules.market_minutes // 60} h in market on {len(short)} of the last {len(last)} days worked: "
                                           + ", ".join(f"{_fmt(x.d)} {x.market // 60}:{x.market % 60:02d}" for x in short[-6:]) + ".",
                    [x.d for x in short])
        if "NO_ACTIVITY" in t.flags:
            na = [x.d for x in last if "NO_ACTIVITY" in x.flags]
            if len(na) >= rules.no_activity_min:
                add("NO_ACTIVITY_REPEAT", f"Marked attendance with no market activity on {len(na)} of the last {len(last)} days worked: "
                                          f"{_dates(na)}.", na)
        if "DAY_NOT_CLOSED" in t.flags:
            nc = [x.d for x in last if "DAY_NOT_CLOSED" in x.flags]
            if len(nc) >= rules.not_closed_min:
                add("DAY_NOT_CLOSED_REPEAT", f"Did not close the day on {len(nc)} of the last {len(last)} days worked: {_dates(nc)}.", nc)
    if t.status in WORKED and t.geo_high:
        last = worked[-10:]
        loc = [x.d for x in last if x.geo_high]
        if len(loc) >= rules.location_min:
            add("LOCATION_REPEAT", f"Serious location signs on {len(loc)} of the last {len(last)} days worked: {_dates(loc)}.", loc)

    if t.status == "ABSENT" and len(due) >= rules.drop_recent + rules.drop_before:
        recent, before = due[-rules.drop_recent:], due[-(rules.drop_recent + rules.drop_before):-rules.drop_recent]

        def pct(xs: list[Day]) -> float:
            return 100 * sum(1 for x in xs if x.status in WORKED) / len(xs)
        r, b = pct(recent), pct(before)
        if b - r >= rules.drop_points and r < rules.drop_recent_max:
            add("ATTENDANCE_DROP", f"Attendance {r:.0f}% on the last {len(recent)} working days ({_fmt(recent[0].d)} to {_fmt(recent[-1].d)}), "
                                   f"was {b:.0f}% on the {len(before)} working days before.", [x.d for x in recent if x.status == "ABSENT"])
    out.sort(key=lambda p: ("high", "medium", "low").index(p["level"]))
    return out


def day_patterns(session: Session, day: date, codes: set[str] | None, supervisors: set[str] | None = None,
                 rules: Rules = Rules()) -> dict[str, list[dict]]:
    """code -> the patterns that person adds to on `day`. `supervisors`: codes of supervisors (no market-activity patterns)."""
    out = {}
    for code, days in history(session, day, codes).items():
        field_role = code not in (supervisors or set())
        ps = person(days, day, rules, field_role)
        if not ps:
            continue
        # shown at most once in `quiet_days`: drop a pattern that was already true on one of the person's previous days
        before = set()
        for i in range(len(days) - 2, -1, -1):
            if (day - days[i].d).days >= rules.quiet_days:
                break
            before |= {p["code"] for p in person(days[:i + 1], days[i].d, rules, field_role)}
        ps = [p for p in ps if p["code"] not in before]
        if ps:
            out[code] = ps
    return out


def team_trend(session: Session, day: date, codes: set[str] | None, weeks: int = 4) -> list[dict]:
    """Attendance % per team head for the last `weeks` rolling weeks (7 days each, ending on `day`), oldest first, from the
    uploaded days (week offs / holidays are left out, as everywhere). A team head needs 3+ people to be shown."""
    from collections import Counter

    from database.models.sales import SalesEmployee
    from sales.report import manager_label
    start = day - timedelta(days=7 * weeks - 1)
    q = (select(SalesDayUpload.report_date, SalesEmployeeDay.code, SalesEmployeeDay.status, SalesEmployeeDay.manager_name)
         .join(SalesDayUpload, SalesDayUpload.upload_id == SalesEmployeeDay.upload_id)
         .where(SalesDayUpload.is_current.is_(True), SalesDayUpload.report_date >= start, SalesDayUpload.report_date <= day))
    staff = {e.code: e.manager_name for e in session.scalars(select(SalesEmployee))}
    c: dict[str, list[Counter]] = defaultdict(lambda: [Counter() for _ in range(weeks)])
    people: dict[str, set[str]] = defaultdict(set)
    for d, code, st, mgr in session.execute(q):
        if codes is not None and code not in codes:
            continue
        th = manager_label(staff.get(code) or mgr) or "No team head"
        w = weeks - 1 - (day - d).days // 7
        c[th][w][st] += 1
        people[th].add(code)

    def pct(x: Counter) -> float | None:
        due = sum(x.values()) - x["WEEK_OFF"]
        return round(100 * (x["PRESENT"] + x["LATE"] + 0.5 * x["HALF_DAY"]) / due, 1) if due else None
    out = []
    for th, ws in c.items():
        if len(people[th]) < 3:
            continue
        p = [pct(x) for x in ws]
        before = [x for x in p[:-1] if x is not None]
        avg = round(sum(before) / len(before), 1) if before else None
        out.append({"team_head": th, "people": len(people[th]), "weeks": p,
                    "week_ranges": [f"{(day - timedelta(days=7 * (weeks - 1 - i) + 6)):%d-%b}–{(day - timedelta(days=7 * (weeks - 1 - i))):%d-%b}"
                                    for i in range(weeks)],
                    "before_avg": avg, "change": round(p[-1] - avg, 1) if p[-1] is not None and avg is not None else None})
    out.sort(key=lambda x: (x["change"] if x["change"] is not None else 0, x["team_head"]))
    return out


def absent_details(session: Session, day: date, codes: set[str] | None) -> dict[str, dict]:
    """For everyone absent on `day`: the last day they worked (from the uploaded days) and how many working days in a row
    they have been absent (week offs, leave and holidays do not break or add to the count)."""
    out = {}
    for code, days in history(session, day, codes, days_back=400).items():
        if not days or days[-1].d != day or days[-1].status != "ABSENT":
            continue
        streak, last = 0, None
        for x in reversed(days):
            if x.status in WORKED:
                last = x.d
                break
            if x.status == "ABSENT":
                streak += 1
        out[code] = {"streak": streak, "last_marked": f"{last:%d-%b-%Y}" if last else None}
    return out
