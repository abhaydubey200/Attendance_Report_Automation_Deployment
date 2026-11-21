"""Module 2: bulk history load (no emails for past days), the new GPS / odd-hour signs, and the email trend + repeats.
Synthetic people and places only."""

from __future__ import annotations

import json
from datetime import date

from database.connection import session_scope
from database.models.sales import SalesCall, SalesDayUpload, SalesEmployeeDay, SalesMailItem
from sales import backfill, checks, mail, report, service, staff
from tests.integration.test_sales_geo import BASE, PEOPLE, STAFF_HEAD, csv_bytes, history_csv, off

ATT_HEAD = ["Zone", "Date", "Emp Name", "Emp Id", "Emp Designation", "Reporting_Manager", "Status", "Leave Details", "Attendance Image",
            "Attendance Time", "First Transaction Time", "Variance(Metres)", "Last Transaction Time", "Time Spent In Market", "KM_traveled",
            "END TIME", "Photograph Status", "User_Status"]


def attendance(d: str, missing: set[str] = frozenset(), early: str | None = None) -> bytes:
    rows = [["Z1", d, n, c, "SO", "Ravi", "present", "", "", "06:10:00" if c == early else "09:00:00", "09:30:00", "0", "18:00:00",
             "08:00:00", "20", "06:30 PM", "Yes", "Active"] for c, n in PEOPLE.items() if c not in missing]
    return csv_bytes(ATT_HEAD, rows)


def eod(days: list[str]) -> bytes:
    head = ["Zone", "User_Name", "Status", "Attendance_Image", "Attendance_Time", "For_Date", "Attendance", "Present_Type", "Leave_Details",
            "Location", "Beat_Name", "EOD_Time", "EOD_Location", "User_Status"]
    at = {"SL00001": BASE, "SL00002": BASE, "SL00003": off(3), "SL00004": off(5, 5), "SL00005": off(-5)}
    return csv_bytes(head, [["Z1", n, "Marked", "", "09:00:00", d, "present", "", "", f"{at[c][0]},{at[c][1]}", "", "18:30:00",
                             f"{at[c][0]},{at[c][1]}", "Active"] for d in days for c, n in PEOPLE.items()])


def calls(d: str, codes: list[str], start_id: int) -> bytes:
    head = ["Zone", "Call_ID", "User_Name", "EMP_Id", "Outlet_Id", "Outlet_Name", "Beat_ID", "Beat_Name", "Outlet_Latitude", "Outlet_Longitude",
            "Call_Latitude", "Call_Longitude", "Distance_Variance(Mtrs)", "Call_Start_Date", "Call_Start_Time", "Call_End_Time", "Total_Time_Spent",
            "Call_Status", "Order_Type", "Reason_Category_Name", "Order_Value"]
    rows, n = [], start_id
    for c in codes:
        for i in range(3):
            n += 1
            p = off(i * 0.5)
            rows.append(["Z1", str(n), c, c, f"O{c}{i}", "Shop", "B1", "Beat", p[0], p[1], p[0], p[1], "0", d, f"1{i}:00:00", f"1{i}:10:00",
                         "0:10:0", "PC", "Normal", "", "100"])
    return csv_bytes(head, rows)


def test_backfill_folder_no_emails_signs_and_email_context(engine, tmp_path):
    with session_scope(engine) as s:
        staff.import_rows(s, [STAFF_HEAD] + [[c, n, "SO", "Z1", "Ravi", "ravi@example.com", "Hod One", "hod1@example.com", "Active"]
                                            for c, n in PEOPLE.items()], "tester", "test")
    folder = tmp_path / "bizom"
    (folder / "nov").mkdir(parents=True)
    (folder / "AttendanceReport.csv").write_bytes(history_csv())                       # 5-17 Nov history (usual places, phones)
    days = ["2026-11-18", "2026-11-19", "2026-11-20"]
    for d in days:                                                                       # Esha absent all three days; Asha marks at 6:10 AM on 20-Nov
        (folder / "nov" / f"Attendancereport-{d}.csv").write_bytes(attendance(d, missing={"SL00005"}, early="SL00001" if d == days[-1] else None))
    (folder / "nov" / "AttendanceAndEOD-3days.csv").write_bytes(eod(days))             # one export covering three days: split by date
    (folder / "nov" / "CallVariance-20-part1.csv").write_bytes(calls(days[-1], ["SL00001", "SL00002"], 0))
    (folder / "nov" / "CallVariance-20-part2.csv").write_bytes(calls(days[-1], ["SL00003"], 100))   # parts of one day: joined
    (folder / "notes.csv").write_bytes(b"a,b\n1,2\n")

    res = backfill.load(engine, folder, "tester", progress=lambda *_: None)
    assert res["history_files"] == 1 and res["days_loaded"] == 3 and res["days_skipped"] == 0 and len(res["problems"]) == 1
    with session_scope(engine) as s:
        assert s.query(SalesMailItem).count() == 0                                       # past days: no emails prepared
        assert s.query(SalesDayUpload).filter_by(is_current=True).count() == 3
        assert s.query(SalesCall).filter_by(day=date(2026, 11, 20)).count() == 9
        r20 = {r.code: r for r in s.query(SalesEmployeeDay).join(SalesDayUpload).filter(SalesDayUpload.report_date == date(2026, 11, 20))}
        assert "ODD_HOUR" in (r20["SL00001"].flags or "")
        assert "GEO_SAME_POINT" in (r20["SL00001"].geo_flags or "") and "GEO_SAME_POINT" in (r20["SL00002"].geo_flags or "")
        assert "GEO_GPS_FROZEN" in (r20["SL00004"].geo_flags or "")                       # exactly the same point every day
        assert "Exactly the same GPS point as on" in json.loads(r20["SL00004"].geo_evidence)["GEO_GPS_FROZEN"]
        # loading again skips the days already there
        assert backfill.load(engine, folder, "tester", progress=lambda *_: None)["days_loaded"] == 0
        # email context for 20-Nov: trend vs 19-Nov and Esha absent three uploaded days in a row
        ctx = checks.context(s, date(2026, 11, 20), None)
        assert ctx["prev_date"] == date(2026, 11, 19) and ctx["streaks"] == [("Esha Fine", 3)]
        up = service.current_upload(s, date(2026, 11, 20))
        v = report.build_view(service.rows_for(s, up.upload_id), json.loads(up.summary), "team", "Ravi", up.report_date, ctx=ctx)
        assert v["trend"].startswith("same as 19-Nov") and "company" in v["trend"]
        assert any("Absent several days in a row: Esha Fine (3 days)" in h["text"] for h in v["highlights"])
        mail.plan(s, up)                                                                  # today's day can still be planned normally
        assert s.query(SalesMailItem).count() > 0
