"""Head Office (Module 1) 30-day insights pack for the emailed dashboard and Excel: the daily trend, each person's 30-day
strip / usual in-time / average hours, a weekday heatmap and (Director / HR only) a scorecard per HOD.
Counted exactly like the daily numbers (daily.analysis): on duty, work from home (and a missing punch when the rule says so)
count as present, half days as half; week offs, holidays and 'not tracked' are left out. Days when most people are on a week
off / holiday are left out of every % (they stay visible in each person's strip)."""

from __future__ import annotations

import statistics
from collections import Counter, defaultdict
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from database.models.daily import DayUpload, EmployeeDay

CODE = {"PRESENT": "P", "MISSING_PUNCH": "M", "ON_DUTY": "D", "WFH": "W", "HALF_DAY": "H", "LEAVE": "V", "ABSENT": "A",
        "WEEK_OFF": "O", "HOLIDAY": "O", "NOT_TRACKED": "N"}
UNCOUNTED = ("WEEK_OFF", "HOLIDAY", "NOT_TRACKED")
WEEKDAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")


def pct(c: Counter, single_punch_present: bool = True) -> float | None:
    tracked = sum(c.values()) - sum(c[s] for s in UNCOUNTED)
    eq = c["PRESENT"] + c["ON_DUTY"] + c["WFH"] + (c["MISSING_PUNCH"] if single_punch_present else 0) + 0.5 * c["HALF_DAY"]
    return round(100 * eq / tracked, 1) if tracked else None


def _mins(hhmm: str | None) -> int | None:
    try:
        h, m = (hhmm or "").split(":")[:2]
        return int(h) * 60 + int(m)
    except ValueError:
        return None


def _t12(m: float | None) -> str:
    if m is None:
        return ""
    m = int(round(m))
    return f"{(m // 60) % 12 or 12}:{m % 60:02d} {'AM' if m < 720 else 'PM'}"


def pack(session: Session, day: date, codes: set[str], group_of: dict[str, str] | None = None, single_punch_present: bool = True,
         n_days: int = 30) -> dict:
    """codes: the recipient's people (upper-case EMP_CODEs). group_of: code -> HOD (Director / HR company views only)."""
    q = (select(DayUpload.report_date, EmployeeDay.employee_code, EmployeeDay.status, EmployeeDay.in_time, EmployeeDay.work_minutes,
                EmployeeDay.flags)
         .join(EmployeeDay, EmployeeDay.upload_id == DayUpload.upload_id)
         .where(DayUpload.is_current.is_(True), DayUpload.report_date <= day, DayUpload.report_date > day - timedelta(days=95)))
    rows = [(d, c.upper(), st, it, wm, fl) for d, c, st, it, wm, fl in session.execute(q) if c.upper() in codes]
    tot: dict[date, Counter] = defaultdict(Counter)
    for d, _, st, *_ in rows:
        tot[d][st] += 1
    off = {d for d, c in tot.items() if (c["WEEK_OFF"] + c["HOLIDAY"]) > 0.5 * sum(c.values())}
    last = sorted(tot)[-n_days:]
    idx = {d: i for i, d in enumerate(last)}
    per: dict[str, dict] = defaultdict(lambda: {"strip": ["-"] * len(last), "c": Counter(), "late": 0, "ins": [], "work": []})
    heat: dict[str, list[Counter]] = defaultdict(lambda: [Counter() for _ in range(7)])
    grp30: dict[str, Counter] = defaultdict(Counter)
    for d, code, st, it, wm, fl in rows:
        p = per[code]
        if d in idx:
            p["strip"][idx[d]] = CODE.get(st, "-")
            if d not in off:
                p["c"][st] += 1
                p["late"] += "LATE" in (fl or "")
                if wm:
                    p["work"].append(wm)
                if group_of and code in group_of:
                    grp30[group_of[code]][st] += 1
        if st in ("PRESENT", "MISSING_PUNCH") and (m := _mins(it)) is not None:
            p["ins"].append(m)
        if d not in off and (day - d).days < 84:
            heat["Everyone"][d.weekday()][st] += 1
            if group_of and code in group_of:
                heat[group_of[code]][d.weekday()][st] += 1
    people = {}
    for code, p in per.items():
        c = p["c"]
        people[code] = {"strip": "".join(p["strip"]), "pct30": pct(c, single_punch_present), "late30": p["late"], "absent30": c["ABSENT"],
                        "leave30": c["LEAVE"] + c["HALF_DAY"], "wfh_od30": c["WFH"] + c["ON_DUTY"],
                        "usual_in": _t12(statistics.median(p["ins"])) if len(p["ins"]) >= 5 else "",
                        "avg_hours": (lambda w: f"{int(w // 60)}:{int(w % 60):02d}")(sum(p["work"]) / len(p["work"])) if p["work"] else ""}
    trend = [{"date": d.isoformat(), "label": f"{d.day}-{d:%b}", "weekday": WEEKDAYS[d.weekday()],
              "pct": None if d in off else pct(tot[d], single_punch_present), "off_day": d in off, "absent": tot[d]["ABSENT"],
              "late": None, "people": sum(tot[d].values())} for d in last]
    late_by_day: Counter = Counter(d for d, _, _, _, _, fl in rows if "LATE" in (fl or ""))
    for t in trend:
        t["late"] = late_by_day[date.fromisoformat(t["date"])]
    groups = []
    if group_of:
        for g, c in grp30.items():
            groups.append({"name": g, "pct30": pct(c, single_punch_present), "absent30": c["ABSENT"], "heat": [pct(w, single_punch_present) for w in heat[g]]})
        groups.sort(key=lambda x: (x["pct30"] if x["pct30"] is not None else 999, x["name"]))
    return {"labels": [f"{d.day}-{d:%b}" for d in last], "weekday_of": [WEEKDAYS[d.weekday()] for d in last], "trend": trend,
            "people": people, "heat_all": [pct(w, single_punch_present) for w in heat["Everyone"]], "weekdays": list(WEEKDAYS),
            "groups": groups}
