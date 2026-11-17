"""Month-end insights: streaks, Monday/Friday clustering, perfect attendance, movers and the takeaways text."""

from __future__ import annotations

from datetime import date, timedelta

from core.config import Rules
from daily import month_insights as mi
from daily import reports

DAYS = [date(2026, 10, 5) + timedelta(days=i) for i in range(12)]          # Mon 05 Oct .. Fri 16 Oct


def _day(d, status, late=False):
    return {"date": d.isoformat(), "status": status, "flags": ["LATE"] if late else [], "in_time": "09:10" if status == "PRESENT" else None,
            "work_hours": 9.0 if status == "PRESENT" else None, "leave_type": "PL" if status == "LEAVE" else None}


def _people(spec):
    """spec: code -> list of status per day ('P', 'A', 'L', 'Lt' = present but late)."""
    by_code, people = {}, []
    for code, codes in spec.items():
        per = {d: _day(d, {"P": "PRESENT", "A": "ABSENT", "L": "LEAVE", "Lt": "PRESENT"}[c], c == "Lt") for d, c in zip(DAYS, codes)}
        by_code[code] = per
        t = reports._tally(list(per.values()), Rules())
        people.append({"code": code, "name": f"Name {code}", **t})
    return people, by_code


def test_patterns_and_takeaways():
    P = "P"
    people, by_code = _people({
        "S1": ["A", "A", "A", "A", P, P, P, P, P, P, P, P],          # 4-day absence run starting Monday
        "M1": ["A", P, P, P, "A", "A", P, P, P, P, P, P],            # Mon 5, Fri 9, Sat 10 absent -> 2 of 3 on Mon/Fri
        "OK": [P] * 12,                                               # perfect
        "LV": [P, P, "L", P, P, P, P, P, P, P, P, P],                 # leave -> not perfect
        "LT": ["Lt", "Lt", P, P, P, P, P, P, P, P, P, P],
    })
    st = mi.streaks(people, DAYS, by_code)
    assert [(s["code"], s["days"], s["from"]) for s in st] == [("S1", 4, DAYS[0])]
    assert [m["code"] for m in mi.monday_friday(people, DAYS, by_code)] == ["M1"]
    assert [p["code"] for p in mi.perfect(people)] == ["OK"]
    prev = {"OK": {"attendance_pct": 80.0}, "S1": {"attendance_pct": 95.0}}
    up, down = mi.movers(people, prev)
    assert [u["code"] for u in up] == ["OK"] and [d["code"] for d in down] == ["S1"]
    totals = reports._tally([d for per in by_code.values() for d in per.values()], Rules())
    ins = mi.build(people, DAYS, by_code, Rules(), totals, {"attendance_pct": 95.0}, prev)
    text = " ".join(t["text"] for t in ins["takeaways"])
    assert "below the 90% target" in text and "on last month" in text
    assert "absent 3+ report days in a row: Name S1 (4 days)" in text
    assert "Mondays / Fridays (Name M1)" in text and "perfect attendance" in text and "late arrival" in text
    assert ins["leave_mix"] == [{"type": "PL", "days": 1}]
    assert {w["day"] for w in ins["weekday"]} >= {"Monday", "Friday"} and len(ins["weeks"]) == 2
    assert "today" not in text.lower()
