"""Module 2 counting: nobody is absent before joining; Sundays / holidays (most staff not marked) are not absences;
the EOD report is matched on EMP_CODE first. Synthetic people only."""

from __future__ import annotations

from datetime import date

from database.models.sales import SalesEmployee
from sales.analysis import analyse
from sales.bizom import AttendanceRow, BizomFile, EodRow
from sales.config import SalesRules


def staff(n: int, doj: date = date(2026, 1, 1)) -> list[SalesEmployee]:
    return [SalesEmployee(code=f"SL{i:05d}", name=f"Person {i}", designation="SO", status="ACTIVE", date_of_joining=doj) for i in range(n)]


def att(day: date, codes: list[str]) -> BizomFile:
    rows = [AttendanceRow(code=c, name=f"Person {int(c[2:])}", designation="SO", zone="Z", manager="M", asm=None, status="present",
                          leave=None, attendance_time="09:30", first_activity="10:00", last_activity="18:00", market_minutes=420, km=20,
                          end_time="18:30", variance_m=0, photo=True, active=True) for c in codes]
    return BizomFile("ATTENDANCE", day, attendance=rows)


def status_of(res) -> dict[str, str]:
    return {p.code: p.status for p in res.people}


def test_not_absent_before_joining():
    people = staff(10) + [SalesEmployee(code="SL09999", name="New Joiner", designation="SO", status="ACTIVE",
                                        date_of_joining=date(2026, 11, 20))]
    res = analyse(att(date(2026, 11, 18), [e.code for e in people[:8]]), None, None, people, SalesRules())   # a Wednesday
    st = status_of(res)
    assert "SL09999" not in st and res.summary["not_yet_joined"] == 1
    assert st["SL00008"] == "ABSENT" and res.summary["off_day"] is None


def test_sunday_and_holiday_are_not_absences():
    people = staff(10)
    sun = analyse(att(date(2026, 11, 22), ["SL00000"]), None, None, people, SalesRules())
    st = status_of(sun)
    assert sun.summary["off_day"] == "Sunday" and st["SL00000"] == "PRESENT" and st["SL00005"] == "WEEK_OFF"
    assert next(p for p in sun.people if p.code == "SL00005").leave_type == "Sunday"
    hol = analyse(att(date(2026, 10, 20), ["SL00000", "SL00001", "SL00002"]), None, None, people, SalesRules())   # Tuesday, 3 of 10
    assert hol.summary["off_day"].startswith("Holiday (only 3 of 10") and status_of(hol)["SL00009"] == "WEEK_OFF"
    normal = analyse(att(date(2026, 10, 21), [e.code for e in people[:6]]), None, None, people, SalesRules())   # 6 of 10
    assert normal.summary["off_day"] is None and status_of(normal)["SL00009"] == "ABSENT"


def test_eod_is_matched_on_code_before_name():
    people = staff(2)
    day = date(2026, 11, 18)
    a = att(day, ["SL00000", "SL00001"])
    a.attendance[1].name = "Person 0"                       # two people with the same name, different codes
    eod = BizomFile("EOD", day, eod=[EodRow(name="Person 0", marked=True, attendance_time="09:30", eod_time="19:15", code="SL00001"),
                                     EodRow(name="Person 0", marked=True, attendance_time="09:30", eod_time="18:05", code="SL00000")])
    res = analyse(a, eod, None, people, SalesRules())
    by = {p.code: p for p in res.people}
    assert by["SL00000"].eod_time == "18:05" and by["SL00001"].eod_time == "19:15"
