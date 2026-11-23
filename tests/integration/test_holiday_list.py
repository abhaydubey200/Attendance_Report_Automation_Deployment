"""HR's yearly holiday list (PDF): reading + checks, Module 1 (Delhi / HO page) and Module 2 (each person's state).
Synthetic pages and people only."""

from __future__ import annotations

import json
from datetime import date

import pytest

from daily import analysis, holiday_list as hl
from database.connection import session_scope

HO_PAGE = """Name
HOLIDAY LIST 2026 01st January 2026
UP/MP/Chhattisgarh/Himachal/Punjab/ Haryana /J&K/Orissa/Delhi/HO
Holidays List For the Year 2026
Sr No. Month Date Day Festivals
1 January 26-Jan-2026 Monday Republic Day
2 October 20-Oct-2026 Tuesday Dussehra/VIJAYADASAMI
3 November 18-Nov-2026 Wednesday Test Holiday
Note: something"""
PLANT_PAGE = """HOLIDAY LIST 2026 01st January 2026
Plant/ Uttrakhand
Holidays List For the Year 2026
Sr No. Month Date Day Festivals
1 August 11-Aug-25 Tuesday Shivaratri"""
SOUTH_PAGE = """HOLIDAY LIST 2026 01st January 2026
Andhra Pradesh , Telangana & Karnataka
Holidays List For the Year 2026
Sr No. Month Date Day Festivals
1 October 21-Oct-2026 Tuesday VIJAYADASAMI
2 November 18-Nov-2026 Wednesday South Holiday"""


def parsed():
    return hl.parse_pages([HO_PAGE, PLANT_PAGE, SOUTH_PAGE])


def test_reads_regions_states_and_checks_every_line():
    r = parsed()
    assert r["year"] == 2026 and [x["page"] for x in r["regions"]] == [1, 2, 3]
    assert r["regions"][0]["states"][-3:] == ["Odisha", "Delhi", "Head Office"] and "Jammu and Kashmir" in r["regions"][0]["states"]
    assert r["regions"][2]["states"] == ["Andhra Pradesh", "Telangana", "Karnataka"]
    shiv = r["regions"][1]["holidays"][0]
    assert shiv["date"] == "2026-08-11" and shiv["fixed"] and "read as 11-Aug-2026" in shiv["issue"]      # year typo, weekday proves it
    vd = r["regions"][2]["holidays"][0]
    assert vd["date"] == "2026-10-21" and not vd["fixed"] and "is a Wednesday, the list says Tuesday" in vd["issue"]
    assert r["open_issues"] == 1
    with pytest.raises(hl.HolidayListError, match="No holiday list"):
        hl.parse_pages(["just some text"])
    with pytest.raises(hl.HolidayListError, match="not a PDF"):
        hl.read_pdf(b"hello")


def test_open_issue_is_not_used_until_hr_confirms(engine):
    with session_scope(engine) as s:
        hl.save(s, parsed(), "list.pdf", "hr")
        assert hl.holidays_on(s, date(2026, 10, 21), "Karnataka") is None                 # date / weekday mismatch: not used
        hl.fix(s, 2026, "Andhra Pradesh , Telangana & Karnataka", "2026-10-21", "2026-10-20", None, "hr")
        assert hl.holidays_on(s, date(2026, 10, 20), "Karnataka") == "VIJAYADASAMI"
        assert hl.holidays_on(s, date(2026, 8, 11), "Uttarakhand") == "Shivaratri"       # corrected typo is used
        assert hl.head_office_holiday(s, date(2026, 10, 20)) == "Dussehra/VIJAYADASAMI"
        assert hl.head_office_holiday(s, date(2026, 8, 11)) is None                      # Plant page is not Module 1's


def test_module1_fills_people_pocket_hrms_missed_and_flags_unlisted_days():
    from tests.integration.test_daily import _classify
    d, results, _ = _classify()
    by = {r.code: r for r in results}
    assert by["E5"].status == "ABSENT"
    out = analysis.apply_holiday_list(results, "Dussehra")
    assert out["added"] >= 1 and by["E5"].status == "HOLIDAY" and by["E5"].day_portion == "Dussehra"
    assert by["E1"].status == "PRESENT" and by["E7"].status == "LEAVE"                  # punched / on leave: unchanged
    d, results, _ = _classify()
    assert analysis.apply_holiday_list(results, None)["added"] == 0


def test_module2_state_holiday_per_person_and_self_check(engine):
    from database.models.sales import SalesEmployee
    from sales import holiday_states, service, staff
    from tests.integration.test_sales_backfill import attendance
    from tests.integration.test_sales_geo import PEOPLE, STAFF_HEAD
    with session_scope(engine) as s:
        hl.save(s, parsed(), "list.pdf", "hr")
        staff.import_rows(s, [STAFF_HEAD] + [[c, n, "SO", "Z1", "Ravi", "ravi@example.com", "Hod One", "hod1@example.com", "Active"]
                                            for c, n in PEOPLE.items()], "tester", "test")
        codes = list(PEOPLE)
        holiday_states.set_state(s, codes[0], "Karnataka", "hr")                       # South Holiday on 18-Nov
        holiday_states.set_state(s, codes[1], "Delhi", "hr")                           # Test Holiday on 18-Nov
        with pytest.raises(ValueError):
            holiday_states.set_state(s, codes[2], "Atlantis", "hr")
        up = service.process(s, [("a.csv", attendance("2026-11-18", missing={codes[0], codes[1], codes[4]}))], "tester", plan_mail=False)
        rows = {r.code: r for r in s.query(__import__("database.models.sales", fromlist=["x"]).SalesEmployeeDay).filter_by(upload_id=up.upload_id)}
        assert rows[codes[0]].status == "WEEK_OFF" and rows[codes[0]].leave_type == "Holiday – South Holiday"
        assert rows[codes[1]].status == "WEEK_OFF" and rows[codes[4]].status == "ABSENT"   # no state: absent as before
        summ = json.loads(up.summary)
        assert summ["verify"]["mismatch_count"] == 0 and summ["state_holidays"] == {"South Holiday": 1, "Test Holiday": 1}
        # HR changes a state afterwards: the stored day follows
        from sales import calendar
        holiday_states.set_state(s, codes[0], None, "hr")
        calendar.apply_year(s, 2026, "hr")
        rows = {r.code: r.status for r in s.query(__import__("database.models.sales", fromlist=["x"]).SalesEmployeeDay).filter_by(
            upload_id=service.current_upload(s, date(2026, 11, 18)).upload_id)}
        assert rows[codes[0]] == "ABSENT"
        assert s.query(SalesEmployee).filter_by(code=codes[1]).one().holiday_state_by == "HR (hr)"


def test_gps_suggestion_needs_a_clear_margin():
    region_of = {"Karnataka": "South", "Tamil Nadu": "TN", "Delhi": "North", "Uttar Pradesh": "North", "Haryana": "North"}.get
    from sales.holiday_states import suggest_for
    s = suggest_for((12.97, 77.60), lambda st: region_of(st, st))                       # central Bengaluru
    assert s["state"] == "Karnataka" and s["sure"]
    s = suggest_for((12.80, 77.75), lambda st: region_of(st, st))                       # between Bengaluru and Hosur (TN)
    assert not s["sure"] and {s["state"], s["other"]} == {"Karnataka", "Tamil Nadu"}       # border: HR chooses
    s = suggest_for((28.55, 77.25), lambda st: region_of(st, st))                       # Delhi / Noida / Gurugram: same holiday list
    assert s["sure"] and region_of(s["state"]) == "North"


def test_api_preview_upload_and_fix(settings, engine, tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from api.main import create_app
    from tests.integration.test_api import H, with_auth_mode
    monkeypatch.setattr(hl, "read_pdf", lambda data: parsed())
    with TestClient(create_app(with_auth_mode(settings, "none"), engine, frontend_dist=tmp_path / "no-dist")) as c:
        r = c.post("/api/v1/holidays/preview", files={"file": ("Holiday List 2026.pdf", b"%PDF-1.4")}, headers=H)
        assert r.status_code == 200 and r.json()["open_issues"] == 1
        assert c.get("/api/v1/holidays").json()["years"] == []                           # preview saves nothing
        r = c.post("/api/v1/holidays/upload", files={"file": ("Holiday List 2026.pdf", b"%PDF-1.4")}, headers=H)
        body = r.json()
        assert r.status_code == 200 and body["year"] == 2026 and [h["name"] for h in body["head_office"]][1] == "Dussehra/VIJAYADASAMI"
        r = c.put("/api/v1/holidays/2026/fix", json={"region": "Andhra Pradesh , Telangana & Karnataka", "old": "2026-10-21",
                                                      "new": "2026-10-20"}, headers=H)
        assert r.status_code == 200 and r.json()["open_issues"] == 0


def test_date_on_every_page_is_a_company_holiday(engine):
    with session_scope(engine) as s:
        hl.save(s, parsed(), "list.pdf", "hr")
        assert hl.company_holiday(s, date(2026, 11, 18)) is None          # not on the Plant page
        assert hl.company_holiday(s, date(2026, 1, 26)) is None           # not on Plant / South pages
        both = hl.parse_pages([HO_PAGE, SOUTH_PAGE])
        hl.save(s, both, "list.pdf", "hr")
        assert hl.company_holiday(s, date(2026, 11, 18)) in ("Test Holiday", "South Holiday")
