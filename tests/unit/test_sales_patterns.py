"""Field Sales patterns: plain counts over a person's own days, each with its dates. Synthetic days only."""

from __future__ import annotations

from datetime import date, timedelta

from sales.patterns import Day, Rules, person

MON = date(2026, 11, 2)          # a Monday


def days(spec: dict[int, str], start: date = MON, n: int = 60, **extra) -> list[Day]:
    """n calendar days from `start`; Sundays are week offs; spec: day index -> status (default PRESENT)."""
    out = []
    for i in range(n):
        d = start + timedelta(days=i)
        st = "WEEK_OFF" if d.weekday() == 6 else spec.get(i, "PRESENT")
        out.append(Day(d, st, None, "09:30" if st in ("PRESENT", "LATE") else None, 420 if st == "PRESENT" else None,
                       **extra.get(i, {})))
    return out


def codes(ps):
    return [p["code"] for p in ps]


def test_nothing_on_a_normal_day_or_a_day_not_uploaded():
    ds = days({})
    assert person(ds, ds[-1].d) == []
    assert person(ds, ds[-1].d + timedelta(days=1)) == []             # only the person's own last uploaded day


def test_absent_on_the_same_weekday_lists_the_dates():
    mondays = [i for i in range(60) if (MON + timedelta(days=i)).weekday() == 0]
    spec = {i: "ABSENT" for i in mondays[-4:]}                       # last 4 Mondays absent (of the last 5)
    ds = days(spec, n=mondays[-1] + 1)
    ps = person(ds, ds[-1].d)
    p = next(x for x in ps if x["code"] == "ABSENT_WEEKDAY")
    assert p["text"].startswith("Absent on 4 of the last 5 Mondays:") and len(p["dates"]) == 4
    assert "ABSENT_REPEAT" not in codes(ps)                          # 4 absences is not 'often'


def test_absent_often_counts_only_working_days():
    spec = {i: "ABSENT" for i in (37, 40, 43, 47, 50, 54)}
    spec.update({i: "LEAVE" for i in (41, 42)})                      # leave is never counted as absent
    ds = days(spec, n=55)
    p = next(x for x in person(ds, ds[-1].d) if x["code"] == "ABSENT_REPEAT")
    assert "on 6 of the last 30 working days" in p["text"]


def test_late_often_shows_the_times_and_needs_late_today():
    spec = {i: "LATE" for i in (50, 51, 52, 53, 54)}
    ds = days(spec, n=55)
    for x in ds[50:55]:
        x.att = "11:05"
    p = next(x for x in person(ds, ds[-1].d) if x["code"] == "LATE_REPEAT")
    assert "Late on 5 of the last 10 working days" in p["text"] and "11:05 AM" in p["text"]
    ds[-1].status = "PRESENT"
    assert "LATE_REPEAT" not in codes(person(ds, ds[-1].d))


def test_short_market_is_for_field_roles_only():
    ds = days({}, n=30)
    for x in ds[-6:]:
        if x.status == "PRESENT":
            x.market = 150
    assert "SHORT_MARKET_REPEAT" in codes(person(ds, ds[-1].d))
    assert "SHORT_MARKET_REPEAT" not in codes(person(ds, ds[-1].d, field_role=False))


def test_attendance_drop_compares_two_periods():
    spec = {i: "ABSENT" for i in range(55, 80) if i % 2}             # about half absent in the recent period
    ds = days(spec, n=80)
    ds[-1].status = "ABSENT"
    p = next(x for x in person(ds, ds[-1].d, Rules()) if x["code"] == "ATTENDANCE_DROP")
    assert "was 100% on the 40 working days before" in p["text"]


def test_same_weekday_needs_to_stand_out_from_other_days():
    mondays = [i for i in range(60) if (MON + timedelta(days=i)).weekday() == 0]
    spec = {i: "ABSENT" for i in range(0, mondays[-1] + 1) if i % 2 == 0}   # absent every other day: Mondays not special
    spec.update({i: "ABSENT" for i in mondays[-4:]})
    ds = days(spec, n=mondays[-1] + 1)
    assert "ABSENT_WEEKDAY" not in codes(person(ds, ds[-1].d))


def test_patterns_reach_the_email_excel_and_dashboard():
    import io as _io
    from types import SimpleNamespace

    from openpyxl import load_workbook

    from sales import report

    row = SimpleNamespace(code="SL00001", name="Asha Rao", designation="SO", zone="Z1", manager_name="Ravi", zonal_name="Zed", hod_name="Hod",
                          status="ABSENT", bizom_status=None, leave_type=None, attendance_time=None, first_activity=None, last_activity=None,
                          market_minutes=None, km=None, eod_time=None, calls=None, productive_calls=None, short_calls=None, far_calls=None,
                          order_value=None, in_master=True, flags=None, attendance_variance_m=None, max_call_distance_m=None,
                          fast_moves=None, beat_jump_calls=None)
    pat = {"SL00001": [{"code": "ABSENT_WEEKDAY", "label": "Absent on the same weekday", "level": "high",
                        "text": "Absent on 4 of the last 5 Mondays: 26-Oct, 2-Nov, 9-Nov, 16-Nov.", "dates": []}]}
    v = report.build_view([row], {"attendance_pct": 90}, "team", "Ravi", date(2026, 11, 16), ctx={"patterns": pat})
    assert any(h["text"].startswith("Repeat patterns (1): Asha Rao – absent on 4 of the last 5 Mondays") for h in v["highlights"])
    wb = load_workbook(_io.BytesIO(report.excel(v)), read_only=True)
    rows = [r for r in wb["Patterns"].iter_rows(values_only=True)]
    assert rows[1][1] == "Asha Rao" and "26-Oct, 2-Nov, 9-Nov, 16-Nov" in rows[1][6]
    assert "Absent on 4 of the last 5 Mondays" in report.dashboard(v).decode()
