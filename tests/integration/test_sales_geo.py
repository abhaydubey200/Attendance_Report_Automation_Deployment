"""Module 2 location checks: points stored, each warning sign, history import (usual start, shared phone), day map, cases,
who may see what, and the 6-month clean-up. Synthetic people and places only."""

from __future__ import annotations

import csv
import io
import json
from datetime import date

import pytest
from fastapi.testclient import TestClient

from api.main import CSRF_HEADER, create_app
from database.connection import session_scope
from database.models.sales import SalesCall, SalesDevice, SalesEmployeeDay, SalesLocation
from database.models.security import AppUser
from sales import geo, service, staff
from security.permissions import Principal

H = {CSRF_HEADER: "1"}
D = "2026-11-18"
BASE = (28.6000, 77.2000)                      # Delhi


def off(km_north: float, km_east: float = 0.0, at=BASE) -> tuple[float, float]:
    return (round(at[0] + km_north / 111.0, 6), round(at[1] + km_east / 97.6, 6))


def csv_bytes(head, rows) -> bytes:
    buf = io.StringIO()
    w = csv.writer(buf, quoting=csv.QUOTE_ALL)
    w.writerow(head)
    w.writerows(rows)
    return buf.getvalue().encode()


PEOPLE = {"SL00001": "Asha Spot", "SL00002": "Bina Shadow", "SL00003": "Chetan Route", "SL00004": "Divya Phone", "SL00005": "Esha Fine"}
KM = {"SL00001": "20", "SL00002": "18", "SL00003": "200", "SL00004": "15", "SL00005": "22"}


def attendance_csv() -> bytes:
    head = ["Zone", "Date", "Emp Name", "Emp Id", "Emp Designation", "Reporting_Manager", "Status", "Leave Details", "Attendance Image",
            "Attendance Time", "First Transaction Time", "Variance(Metres)", "Last Transaction Time", "Time Spent In Market", "KM_traveled",
            "END TIME", "Photograph Status", "User_Status"]
    return csv_bytes(head, [["Z1", D, n, c, "SO", "Ravi", "present", "", f"<a href='https://img.example.com/{c}.jpg'>photo</a>", "09:00:00",
                             "09:30:00", "0", "18:00:00", "08:00:00", KM[c], "06:30 PM", "Yes", "Active"] for c, n in PEOPLE.items()])


def eod_csv() -> bytes:
    head = ["Zone", "User_Name", "Status", "Attendance_Image", "Attendance_Time", "For_Date", "Attendance", "Present_Type", "Leave_Details",
            "Location", "Beat_Name", "EOD_Time", "EOD_Location", "User_Status"]
    start = {"SL00001": BASE, "SL00002": BASE, "SL00003": off(50), "SL00004": off(5, 5), "SL00005": off(-5)}   # Chetan starts 50 km away
    end = {"SL00003": off(90)}                                                                                  # Chetan ends far away
    rows = []
    for c, n in PEOPLE.items():
        s, e = start[c], end.get(c, start[c])
        rows.append(["Z1", n, "Marked", "", "09:00:00", D, "present", "", "", f"{s[0]},{s[1]}", "", "18:30:00", f"{e[0]},{e[1]}", "Active"])
    return csv_bytes(head, rows)


def calls_csv() -> bytes:
    head = ["Zone", "Call_ID", "User_Name", "EMP_Id", "Outlet_Id", "Outlet_Name", "Beat_ID", "Beat_Name", "Outlet_Mobile_No",
            "Outlet_Latitude", "Outlet_Longitude", "Call_Latitude", "Call_Longitude", "Distance_Variance(Mtrs)", "Call_Start_Date",
            "Call_Start_Time", "Call_End_Time", "Total_Time_Spent", "Call_Status", "Order_Type", "Reason_Category_Name", "Order_Value"]
    rows, n = [], 0

    def add(code, outlet, beat, o_at, c_at, start, end):
        nonlocal n
        n += 1
        rows.append(["Z1", str(n), code, code, outlet, f"Shop {outlet}", beat, f"Beat {beat}", "9876543210", o_at[0], o_at[1], c_at[0], c_at[1],
                     "0", D, start, end, "0:5:0", "PC", "Normal", "", "100"])
    # Asha: 6 outlets 1-3 km apart, every call made from her start point
    for i in range(6):
        add("SL00001", f"A{i}", "B1", off(1 + i * 0.4, 0.5), BASE, f"{10 + i}:00:00", f"{10 + i}:05:00")
    # Bina: right next to Asha, same times (her own outlets, also far)
    for i in range(6):
        add("SL00002", f"BB{i}", "B1", off(-2 - i * 0.3), off(0.01), f"{10 + i}:03:00", f"{10 + i}:08:00")
    # Chetan: honest visits along a road, 4 on beat C1, 3 on beat C2 (off beat); KM claimed 200
    for i in range(7):
        p = off(50 + i * 2)
        add("SL00003", f"C{i}", "C1" if i < 4 else "C2", p, p, f"{10 + i}:00:00", f"{10 + i}:10:00")
    # Esha: normal day
    for i in range(5):
        p = off(-5 - i * 2)
        add("SL00005", f"E{i}", "E1", p, off(-5 - i * 2 + 0.05), f"{10 + i}:00:00", f"{10 + i}:20:00")
    return csv_bytes(head, rows)


def history_csv() -> bytes:
    head = ["Zone", "Reporting To", "User_ID", "User Name", "Emp Id", "Designation", "Phone Number", "Status", "Attendance Image",
            "Attendance Time", "EOD_Time", "For Date", "Attendance", "Present_Type", "IMEI", "Leave Details", "Location", "Variance_Kms"]
    rows = []
    for d in range(5, 18):                                     # 13 earlier days: everyone starts at their usual point
        for c, n in PEOPLE.items():
            at = {"SL00003": BASE, "SL00004": off(5, 5), "SL00005": off(-5)}.get(c, BASE)
            rows.append(["Z1", "Ravi", "1", n, c, "SO", "9999999999", "Marked", "", "09:00:00", "18:00:00", f"2026-11-{d:02d}", "present", "",
                         f"35{c[-1]}11122233344", "", f"{at[0]},{at[1]}", "0"])
    for c in ("SL00001", "SL00004"):                           # on the day itself Asha and Divya used the same phone
        rows.append(["Z1", "Ravi", "1", PEOPLE[c], c, "SO", "", "Marked", "", "09:00:00", "", D, "present", "", "356111222333444", "", "", "0"])
    return csv_bytes(head, rows)


STAFF_HEAD = ["Emp Code", "Name", "Designation", "Zone", "Reporting Manager", "Reporting Manager Email", "HOD", "HOD Email", "Status"]


@pytest.fixture
def day(engine):
    with session_scope(engine) as s:
        rows = [[c, n, "SO", "Z1", "Ravi", "ravi@example.com", "Hod One" if c != "SL00005" else "Hod Two",
                 "hod1@example.com" if c != "SL00005" else "hod2@example.com", "Active"] for c, n in PEOPLE.items()]
        staff.import_rows(s, [STAFF_HEAD] + rows, "tester", "test")
        service.process(s, [("a.csv", attendance_csv()), ("e.csv", eod_csv()), ("c.csv", calls_csv())], "tester")
    return engine


def flags(s, code) -> dict:
    r = s.query(SalesEmployeeDay).filter_by(code=code).one()
    return json.loads(r.geo_evidence or "{}")


def test_points_and_call_checks(day):
    with session_scope(day) as s:
        assert s.query(SalesLocation).filter_by(day=date(2026, 11, 18)).count() == 10            # 5 attendance + 5 day end
        assert s.query(SalesCall).count() == 24
        r = s.query(SalesEmployeeDay).filter_by(code="SL00001").one()
        assert r.photo_url == "https://img.example.com/SL00001.jpg"
        assert "9876543210" not in json.dumps([c.__dict__.get("outlet_id") for c in s.query(SalesCall)])
        a = flags(s, "SL00001")
        assert {"GEO_AWAY_FROM_OUTLET", "GEO_SAME_SPOT", "GEO_ONE_SPOT_MANY_OUTLETS", "GEO_TOGETHER"} <= set(a)
        assert "6 of 6 calls" in a["GEO_AWAY_FROM_OUTLET"] and "Bina Shadow" in a["GEO_TOGETHER"]
        c = flags(s, "SL00003")
        assert {"GEO_KM_VS_ROUTE", "GEO_END_AWAY", "GEO_OFF_BEAT"} <= set(c) and "GEO_AWAY_FROM_OUTLET" not in c
        assert flags(s, "SL00005") == {}                                                       # normal day: nothing
        # emails keep their warning signs unchanged (location signs are app-only for now)
        assert all(not (r.flags or "").count("GEO") for r in s.query(SalesEmployeeDay))


def test_history_usual_start_and_shared_phone(day):
    with session_scope(day) as s:
        res = service.import_history(s, "AttendanceReport.csv", history_csv())
        assert res["days"] == 14 and res["days_rechecked"] == 1 and res["locations_added"] == 65
        assert s.query(SalesDevice).filter_by(day=date(2026, 11, 18)).count() == 2
        assert all("356" not in d.device for d in s.query(SalesDevice))                          # IMEI never stored as is
        assert "GEO_START_AWAY" in flags(s, "SL00003") and "Attendance 50." in flags(s, "SL00003")["GEO_START_AWAY"]
        assert "GEO_START_AWAY" not in flags(s, "SL00004")
        assert "Asha Spot" in flags(s, "SL00004")["GEO_SHARED_PHONE"]
        assert geo.device_code("35-61112 22333444") == geo.device_code("356111222333444") and geo.device_code("12") is None
        with pytest.raises(service.UploadError, match="multi-day"):
            service.process(s, [("h.csv", history_csv())], "tester")


def test_visibility_cases_review_and_purge(day):
    with session_scope(day) as s:
        s.add(AppUser(username="hod2", display_name="Hod Two", email="HOD2@example.com"))
        s.flush()
        uid = s.query(AppUser).filter_by(username="hod2").one().user_id
        hod = Principal(uid, "hod2", "Hod Two", permissions=frozenset({"VIEW_INSIGHTS"}))
        hr = Principal(0, "hr", "HR", permissions=frozenset({"VIEW_INSIGHTS", "UPLOAD_AND_SEND"}))
        assert geo.visible_codes(s, hr) is None and geo.visible_codes(s, hod) == {"SL00005"}
        all_cases = geo.cases(s, date(2026, 11, 1), date(2026, 11, 30), None)
        assert {c["code"] for c in all_cases} == {"SL00001", "SL00002", "SL00003"} and all_cases[0]["case"]["status"] == "OPEN"
        assert geo.cases(s, date(2026, 11, 1), date(2026, 11, 30), {"SL00005"}) == []
        done = geo.review(s, "SL00001", date(2026, 11, 18), "OK", "Market lane - shops share one entrance", "hr")
        assert done["status_label"] == "Checked - OK"
        assert geo.cases(s, date(2026, 11, 1), date(2026, 11, 30), None, status="OPEN")[0]["code"] != "SL00001"
        m = geo.day_map(s, date(2026, 11, 18), "SL00001")
        assert len(m["calls"]) == 6 and m["calls"][0]["away"] and m["attendance"]["lat"] == BASE[0] and m["case"]["status"] == "OK"
        assert m["signs"][0]["kind"] == "location" and m["photo_url"].endswith(".jpg")
        res = geo.purge(s, today=date(2027, 7, 1))
        assert res["locations"] == 10 and res["calls"] == 24 and res["photos"] == 5
        assert s.query(SalesEmployeeDay).filter_by(code="SL00001").one().geo_flags        # the warning signs themselves stay


def test_geo_api(day, settings, tmp_path):
    with TestClient(create_app(settings, day, frontend_dist=tmp_path / "x")) as api:
        m = api.get(f"/api/v1/sales/map/{D}/sl00003").json()
        assert m["code"] == "SL00003" and len(m["calls"]) == 7 and any(s["code"] == "GEO_OFF_BEAT" for s in m["signs"])
        assert api.get(f"/api/v1/sales/map/{D}/SL99999").status_code == 404
        cs = api.get("/api/v1/sales/cases").json()
        assert cs["to"] == D and len(cs["cases"]) == 3
        assert api.put(f"/api/v1/sales/cases/{D}/SL00003", headers=H, json={"status": "ACTION", "note": "Spoke to him"}).json()["status"] == "ACTION"
        assert api.put(f"/api/v1/sales/cases/{D}/SL00003", headers=H, json={"status": "MAYBE"}).status_code == 422
        assert api.get("/api/v1/sales/cases?status=ACTION").json()["cases"][0]["code"] == "SL00003"
        day_ = api.get(f"/api/v1/sales/days/{D}").json()
        assert "Calls made away from the outlet" in day_["geo"]["SL00001"] and day_["geo_summary"]["people"] == 3
        r = api.post("/api/v1/sales/history", headers=H, files={"file": ("AttendanceReport.csv", history_csv(), "text/csv")})
        assert r.status_code == 200 and r.json()["phones_added"] == 67
        assert api.post("/api/v1/sales/history", headers=H, files={"file": ("x.csv", b"a,b\n1,2\n", "text/csv")}).status_code == 422
