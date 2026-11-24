"""Module 2 - Field Sales attendance (Bizom): files, counting, warning signs, routing, emails, API. Synthetic data only."""

from __future__ import annotations

import csv
import io
import json
from datetime import date

import pytest
from fastapi.testclient import TestClient
from openpyxl import load_workbook

from api.main import CSRF_HEADER, create_app
from database.connection import session_scope
from database.models.sales import SalesEmployeeDay
from sales import bizom, mail, report, reports, service, staff
from sales.config import SalesEmail, get_email, save_email

H = {CSRF_HEADER: "1"}
D = "2026-11-18"
ATT_HEAD = ["Zone", "Date", "Users Id", "Emp Name", "Emp Id", "Emp Designation", "Distributor", "Reporting_Manager", "ASM/RSM", "Phone No",
            "BEAT PLAN", "Status", "Present_Type", "Leave Details", "Attendance Image", "Attendance Time", "First Transaction Time",
            "Variance(Metres)", "Last Transaction Time", "Time Spent In Market", "KM_traveled", "END TIME", "Photograph Status", "User_Status"]
#            code      name           desig  manager            status     leave              att        first      var   last       market      km      end
PEOPLE = [("SL00001", "Asha Field", "SO", "Ravi Manager", "present", "", "09:10:00", "09:40:00", "0", "18:30:00", "08:50:00", "35.2", "07:00 PM", "Yes"),
          ("SL00002", "Bina Late", "SR", "Vacant_ASE_Delhi_1", "late", "", "10:45:00", "11:00:00", "0", "19:00:00", "08:00:00", "40", "07:30 PM", "Yes"),
          ("SL00003", "Chetan Ghost", "SO", "Ravi Manager", "present", "", "09:05:00", "", "0", "", "", "12", "06:00 PM", "Yes"),
          ("SL00004", "Divya Leave", "SO", "Ravi Manager", "absent", "Privilege Leave", "08:30:00", "", "0", "", "", "", "", "No"),
          ("SL00005", "Esha Off", "SR", "Ravi Manager", "absent", "Weekly Off", "08:31:00", "", "0", "", "", "", "", "No"),
          ("SL00006", "Farhan Far", "SO", "Ravi Manager", "halfday", "", "14:20:00", "14:30:00", "75", "15:10:00", "00:40:00", "310.5", "04:00 PM", "Yes"),
          ("SL00007", "Gopal Boss", "ASM", "Big Boss", "present", "", "09:30:00", "", "0", "", "", "5", "06:30 PM", "Yes"),
          ("AP00001", "Promo One", "Promoter", "Ravi Manager", "present", "", "09:00:00", "09:10:00", "0", "18:00:00", "08:50:00", "1", "06:00 PM", "Yes"),
          ("SL09999", "Zed Unknown", "SO", "Ravi Manager", "present", "", "09:00:00", "09:20:00", "0", "18:00:00", "08:40:00", "20", "06:00 PM", "Yes")]


def csv_bytes(head, rows) -> bytes:
    buf = io.StringIO()
    w = csv.writer(buf, quoting=csv.QUOTE_ALL)
    w.writerow(head)
    w.writerows(rows)
    return buf.getvalue().encode("utf-8")


def attendance_csv(day=D) -> bytes:
    rows = []
    for i, (code, name, des, mgr, st, leave, att, first, var, last, mkt, km, end, photo) in enumerate(PEOPLE):
        rows.append(["GTR01", day, str(100 + i), name, code, des, "", mgr, "Gouri Shankar", "9999999999", "Beat", st, "", leave,
                     "<img src=x>", att, first, var, last, mkt, km, end, photo, "Active"])
    return csv_bytes(ATT_HEAD, rows)


def eod_csv() -> bytes:
    head = ["Zone", "User_Name", "Status", "Attendance_Image", "Attendance_Time", "For_Date", "Attendance", "Present_Type", "Leave_Details",
            "Location", "Beat_Name", "EOD_Time", "EOD_Location", "User_Status"]
    rows = [["GTR01", "Asha Field", "Marked", "", "09:10:00", D, "present", "", "", "28.1,77.2", "", "19:05:00", "28.1,77.2", "Active"],
            ["GTR01", "Chetan Ghost", "Marked", "", "09:05:00", D, "present", "", "", "", "", "23:59:00", "", "Active"],
            ["GTR01", "Hari Missing", "Not Marked", "", "", D, "", "", "", "", "", "", "", "Active"]]
    return csv_bytes(head, rows)


def calls_csv() -> bytes:
    head = ["Zone", "Call_ID", "User_Name", "EMP_Id", "Call_Start_Date", "Call_Start_Time", "Call_End_Time", "Total_Time_Spent",
            "Call_Status", "Order_Type", "Reason_Category_Name", "Distance_Variance(Mtrs)", "Call_Latitude", "Call_Longitude", "Order_Value",
            "Outlet_Mobile_No"]
    rows = [["GTR01", "1", "SL00001", "SL00001", D, "10:00:00", "10:00:20", "0:0:20", "Non PC", "Telephonic", "no_order", "20", "28.60", "77.20", "", "9"],
            ["GTR01", "2", "SL00001", "SL00001", D, "10:05:00", "10:05:30", "0:0:30", "Non PC", "Telephonic", "no_order", "30", "28.61", "77.21", "", "9"],
            ["GTR01", "3", "SL00001", "SL00001", D, "10:10:00", "10:10:40", "0:0:40", "PC", "Normal", "", "450", "28.62", "77.22", "1500", "9"],
            ["GTR01", "4", "SL00001", "SL00001", D, "10:20:00", "10:30:00", "0:10:0", "PC", "Normal", "", "40", "26.90", "80.90", "2500", "9"]]
    return csv_bytes(head, rows)


STAFF_HEAD = ["Emp Code", "Name", "Designation", "Zone", "Reporting Manager", "Reporting Manager Email", "Zonal Head", "Zonal Head Email",
              "HOD", "HOD Email", "Status"]
STAFF = [["SL00001", "Asha Field", "SO", "GTR01", "Ravi Manager", "ravi@example.com", "Zonal One", "zonal1@example.com", "Hod One", "hod1@example.com", "Active"],
         ["SL00002", "Bina Late", "SR", "GTR01", "", "", "Zonal One", "zonal1@example.com", "Hod One", "hod1@example.com", "Active"],
         ["SL00003", "Chetan Ghost", "SO", "GTR01", "Ravi Manager", "ravi@example.com", "Zonal One", "zonal1@example.com", "Hod One", "hod1@example.com", "Active"],
         ["SL00004", "Divya Leave", "SO", "GTR01", "Ravi Manager", "ravi@example.com", "Zonal One", "zonal1@example.com", "Hod One", "hod1@example.com", "Active"],
         ["SL00005", "Esha Off", "SR", "GTR01", "Ravi Manager", "ravi@example.com", "Zonal One", "zonal1@example.com", "Hod One", "hod1@example.com", "Active"],
         ["SL00006", "Farhan Far", "SO", "GTR01", "Ravi Manager", "ravi@example.com", "Zonal Two", "zonal2@example.com", "Hod One", "hod1@example.com", "Active"],
         ["SL00007", "Gopal Boss", "ASM", "GTR01", "", "", "Zonal One", "zonal1@example.com", "Hod One", "hod1@example.com", "Active"],
         ["SL00008", "Hari Missing", "SO", "GTR01", "Ravi Manager", "ravi@example.com", "Zonal One", "zonal1@example.com", "Hod One", "hod1@example.com", "Active"],
         ["SL00010", "Ira Left", "SO", "GTR01", "Ravi Manager", "ravi@example.com", "Zonal One", "zonal1@example.com", "Hod One", "hod1@example.com", "Left"]]


@pytest.fixture
def staffed(engine):
    with session_scope(engine) as s:
        r = staff.import_rows(s, [STAFF_HEAD] + STAFF, "tester", "test")
    assert r["added"] == 9 and not r["problems"]
    return engine


def test_reads_the_three_bizom_reports_without_personal_data():
    a = bizom.parse(bizom.read_rows(attendance_csv(), "a.csv"))
    assert a.kind == bizom.ATTENDANCE and a.report_date == date(2026, 11, 18) and len(a.attendance) == 9
    assert not any("9999999999" in str(vars(r)) or "img" in str(vars(r)) for r in a.attendance)        # phone / photo never kept
    e = bizom.parse(bizom.read_rows(eod_csv(), "e.csv"))
    assert e.kind == bizom.EOD and sum(not x.marked for x in e.eod) == 1
    c = bizom.parse(bizom.read_rows(calls_csv(), "c.csv"), far_call_m=100, max_speed_kmh=60)
    s = c.calls["SL00001"]
    assert (s.calls, s.productive, s.short, s.telephonic, s.far, s.fast_moves) == (4, 2, 3, 2, 1, 1)   # Delhi -> Lucknow in 10 minutes
    assert "28.6" not in str(vars(s)) and "77.2" not in str(vars(s))
    with pytest.raises(bizom.BizomError):
        bizom.parse(bizom.read_rows(b"a,b\n1,2\n", "x.csv"))


def test_day_counting_warnings_and_emails(staffed, settings):
    with session_scope(staffed) as s:
        up = service.process(s, [("a.csv", attendance_csv()), ("e.csv", eod_csv()), ("c.csv", calls_csv())], "tester")
        rows = {r.code: r for r in service.rows_for(s, up.upload_id)}
        sm = json.loads(up.summary)
        # statuses: leave and week off are not absent; staff who did not mark are absent; promoters left out
        assert rows["SL00004"].status == "LEAVE" and rows["SL00004"].leave_type == "Privilege Leave"
        assert rows["SL00005"].status == "WEEK_OFF" and rows["SL00008"].status == "ABSENT" and not rows["SL00008"].bizom_status
        assert "AP00001" not in rows and sm["data"]["excluded"] == {"promoter": 1} and "SL00010" not in rows   # Left: not expected
        assert not rows["SL09999"].in_master and "Zed Unknown (SL09999)" in sm["data"]["not_in_staff_list"]
        # 9 people: (present 4 incl. the supervisor and the unknown code + late 1 + half 0.5) / (9 - 1 week off) = 5.5 / 8
        assert sm["attendance_pct"] == 68.8 and sm["counts"]["ABSENT"] == 1 and sm["counts"]["HALF_DAY"] == 1
        flags = lambda c: set((rows[c].flags or "").split(","))  # noqa: E731
        assert "NO_ACTIVITY" in flags("SL00003") and "DAY_NOT_CLOSED" in flags("SL00003")
        assert flags("SL00007") == {""}                                                  # ASM: supervisor, no activity check
        assert {"HIGH_KM", "FAR_ATTENDANCE", "VERY_SHORT_MARKET"} <= flags("SL00006")
        assert {"SHORT_CALLS", "FAR_CALLS", "FAST_MOVES"} <= flags("SL00001")
        assert rows["SL00001"].eod_time == "19:05" and rows["SL00001"].order_value == 4000
        # emails: manager, two zonal heads, HOD, Director and HR (held: no address)
        items = {i.recipient_key: i for i in mail.items_for(s, up.report_date)}
        assert set(items) == {"ravi@example.com", "zonal1@example.com", "zonal2@example.com", "hod1@example.com", "DIRECTOR", "HR"}
        assert items["DIRECTOR"].status == "HELD" and items["ravi@example.com"].status == "PENDING"
        assert json.loads(items["zonal2@example.com"].content)["codes"] == ["SL00006"]
        html, text, files = mail.render(s, items["ravi@example.com"])
        assert "Needs checking" in html and "not proof" in html and "fraud" not in html.lower() and "today" not in html.lower()
        assert [f.filename.split("_")[-1] for f in files] == ["Manager.xlsx", "dashboard.html"]
        names = load_workbook(io.BytesIO(files[0].content)).sheetnames
        assert names[0] == "Dashboard" and {"Trend", "Last 30 days", "Needs checking", "Location & selfie checks", "Absent", "Team list"} <= set(names)
        wbx = load_workbook(io.BytesIO(files[0].content))
        assert "TeamList" in wbx["Team list"].tables                                    # pivots count from this table
        assert any(str(c.value).startswith("=COUNTIFS(TeamList[") for row in wbx[next(n for n in names if n.startswith("Pivot"))].iter_rows() for c in row)
        assert "9999999999" not in html + text + files[1].content.decode() and "<img src=x>" not in files[1].content.decode()
        hr_html, _, hr_files = mail.render(s, items["HR"])
        assert "Data to fix" in hr_html and "Data issues" in load_workbook(io.BytesIO(hr_files[0].content)).sheetnames
        # test mode: approving saves to the outbox, nothing is sent; a second approve sends nothing
        assert get_email(s).mode == "test"
        done = mail.send_items(s, [i for i in items.values() if i.status == "PENDING"], "tester", settings.storage.area("sales_outbox"))
        assert len(done) == 4 and {i.status for i in done} == {"SAVED"}
        assert mail.send_items(s, list(items.values()), "tester", settings.storage.area("sales_outbox")) == []
        # same day again needs replace; replacing marks unsent emails superseded and plans again (sent ones become duplicates)
        with pytest.raises(service.AlreadyUploaded):
            service.process(s, [("a.csv", attendance_csv())], "tester")
        up2 = service.process(s, [("a.csv", attendance_csv())], "tester", replace=True)
        again = {i.recipient_key: i.status for i in mail.items_for(s, up2.report_date)}
        assert again["ravi@example.com"] == "DUPLICATE" and again["DIRECTOR"] == "HELD"
        assert s.query(SalesEmployeeDay).filter_by(upload_id=up2.upload_id).count() == 9


def test_upload_needs_the_attendance_report_and_one_date(staffed):
    with session_scope(staffed) as s:
        with pytest.raises(service.UploadError, match="Attendance report is required"):
            service.process(s, [("e.csv", eod_csv())], "tester")
        with pytest.raises(service.UploadError, match="different dates"):
            service.process(s, [("a.csv", attendance_csv("2026-11-17")), ("e.csv", eod_csv())], "tester")


def test_staff_import_updates_never_deletes(staffed):
    with session_scope(staffed) as s:
        r = staff.import_rows(s, [["Emp ID", "Employee Name", "HOD Email"], ["SL00001", "Asha F.", "NOT-AN-EMAIL"]], "tester", "t2")
        assert r["updated"] == 1 and r["problem_count"] == 1
        sm = staff.summary(s)
        assert sm["total"] == 9 and sm["active"] == 8 and sm["with_email"]["hod"] == 8      # bad email ignored, nothing wiped
        with pytest.raises(staff.StaffError):
            staff.import_rows(s, [["foo", "bar"], ["1", "2"]], "tester", "bad")


def test_sales_api_end_to_end(staffed, settings, tmp_path):
    with TestClient(create_app(settings, staffed, frontend_dist=tmp_path / "x")) as api:
        files = [("files", ("Attendancereport.csv", attendance_csv(), "text/csv")), ("files", ("EOD.csv", eod_csv(), "text/csv"))]
        r = api.post("/api/v1/sales/upload", headers=H, files=files)
        assert r.status_code == 200, r.text
        day = r.json()
        assert day["report_date"] == D and day["summary"]["attendance_pct"] == 68.8 and len(day["rows"]) == 9
        assert api.post("/api/v1/sales/upload", headers=H, files=files).status_code == 409
        assert api.post("/api/v1/sales/upload", headers=H, files=[("files", ("x.csv", b"a,b\n1,2\n", "text/csv"))]).status_code == 422
        assert api.get("/api/v1/sales/days").json()[0]["report_date"] == D
        m = api.get(f"/api/v1/sales/days/{D}/mail").json()
        assert m["mode"] == "test" and len(m["items"]) == 6
        first = next(i for i in m["items"] if i["status"] == "PENDING")
        assert "Needs checking" in api.get(f"/api/v1/sales/mail/{first['id']}/preview").text
        assert api.get(f"/api/v1/sales/mail/{first['id']}/attachment/excel").status_code == 200
        assert api.get(f"/api/v1/sales/mail/{first['id']}/attachment/dashboard").status_code == 200
        sent = api.post(f"/api/v1/sales/days/{D}/mail/approve", headers=H, json={}).json()
        assert sent["sent_now"] == 4 and {i["status"] for i in sent["items"] if i["key"] != "DIRECTOR" and i["key"] != "HR"} == {"SAVED"}
        assert api.get(f"/api/v1/sales/days/{D}/excel").status_code == 200 and api.get(f"/api/v1/sales/days/{D}/dashboard").status_code == 200
        st = api.get("/api/v1/sales/staff").json()
        assert st["summary"]["active"] == 8 and len(st["staff"]) == 9
        assert api.get("/api/v1/sales/staff/export").status_code == 200
        assert api.post("/api/v1/sales/staff/SL00001/left", headers=H, json={"exit_date": "2026-11-30"}).json()["status"] == "LEFT"
        assert api.post("/api/v1/sales/staff/SL00001/restore", headers=H).json()["status"] == "ACTIVE"
        assert api.put("/api/v1/sales/settings/email", headers=H, json={"mode": "loud"}).status_code == 422
        assert api.put("/api/v1/sales/settings/email", headers=H, json={"director_emails": ["boss@example.com"]}).json()["director_emails"] == ["boss@example.com"]
        assert api.put("/api/v1/sales/settings/rules", headers=H, json={"late_after": "ten"}).status_code == 422
        assert api.put("/api/v1/sales/settings/rules", headers=H, json={"short_market_minutes": 180}).json()["short_market_minutes"] == 180
        # Module 1 is untouched: its upload still refuses a Bizom file, and no Module 1 day or email was created
        m1 = api.post("/api/v1/days/upload", headers=H, files={"file": ("Attendancereport.csv", attendance_csv(), "text/csv")})
        assert m1.status_code == 422                                   # refused (Module 1 reads only Pocket HRMS files)
        assert api.get("/api/v1/days").json() == [] and api.get("/api/v1/emails").json() == []


def test_vacant_manager_label():
    assert report.manager_label("Vacant_TSM_Rajasthan-2") == "Vacant (TSM Rajasthan-2)" and report.manager_label("Ravi") == "Ravi"
    assert SalesEmail().mode == "test"


def test_test_mode_setting_survives(engine):
    with session_scope(engine) as s:
        save_email(s, SalesEmail(mode="live", director_emails=["d@example.com"]), "tester")
        assert get_email(s).mode == "live" and get_email(s).director_emails == ["d@example.com"]


def test_hr_amendment_file_only_field_sales_and_right_names(engine):
    """HR's Employee Amendment file holds the whole company; Sub split ID = team head email, Reporting Manager = name."""
    from sales.routing import display_name
    rows = [[None] * 9,
            [None, "EMPLOYEE CODE", "Employee Name", "Department", "DOJ", "HOD", "Email ID - HOD", "Sub split ID", "Reporting Manager\xa0"],
            [1, "SL00007", "ASIF ALI ANSARI", "GENERAL TRADE", "2017-08-01", "ARUN MISHRA", "arun.mishra@apisindia.com", "asifansari@apisindia.com", "ASIF ALI ANSARI"],
            [2, "SL00100", "TEAM MEMBER", "GENERAL TRADE", "2020-01-01", "ARUN MISHRA", "arun.mishra@apisindia.com", "avdhesh@apisindia.com", "ARUN MISHRA"],
            [3, "SL04274", "VAIBHAV MISHRA", "Alternate Channels", "", "AMIT ANAND", "amit@apisindia.com", "=G269", "AMIT ANAND"],
            [4, "HO0034", "AMIT ANAND", "Director Office", "", "", "", "", ""],
            [5, "RK00255", "SUNIL KUMAR", "Production", "", "VIPUL", "vipul@apisindia.com", "", ""]]
    with session_scope(engine) as s:
        r = staff.import_rows(s, [[("" if c is None else str(c)) for c in row] for row in rows], "tester", "amendment", codes=["^SL"])
        assert r["added"] == 3 and r["not_field_sales"] == 2 and r["problem_count"] == 1          # '=G269' is not an email
        sm = staff.summary(s)
        assert sm["total"] == 3 and sm["with_email"] == {"manager": 2, "asm": 0, "zonal": 0, "hod": 3}
    assert display_name("ARUN MISHRA", "avdhesh@apisindia.com") == "Avdhesh"
    assert display_name("SHAKIL AHMED", "shakeel@apisindia.com") == "SHAKIL AHMED"
    assert display_name("GOURI SHANKAR", "vaibhav.mishra@apisindia.com") == "Vaibhav Mishra"
    assert display_name("ASIF ALI ANSARI", "asifansari@apisindia.com") == "ASIF ALI ANSARI"


def test_staff_add_and_edit(staffed):
    with session_scope(staffed) as s:
        e = staff.add(s, {"code": "sl04650", "name": "New Person", "manager_email": "RAVI@example.com", "date_of_joining": "2026-11-01"}, "tester")
        assert e.code == "SL04650" and e.manager_email == "ravi@example.com" and e.status == "ACTIVE"
        with pytest.raises(staff.StaffError, match="already"):
            staff.add(s, {"code": "SL04650", "name": "Again"}, "tester")
        with pytest.raises(staff.StaffError):
            staff.update(s, "SL04650", {"hod_email": "nope"}, "tester")
        assert staff.update(s, "SL04650", {"zone": "GTR02"}, "tester").zone == "GTR02"
        with pytest.raises(LookupError):
            staff.update(s, "SL77777", {"zone": "x"}, "tester")


def test_inbox_job_reports_and_month_end(staffed, settings, tmp_path):
    from sales import jobs, monthly
    inbox = jobs.inbox_dir(settings)
    inbox.mkdir(parents=True, exist_ok=True)
    (inbox / "Attendancereport.csv").write_bytes(attendance_csv())
    (inbox / "EOD.csv").write_bytes(eod_csv())
    (inbox / "notes.csv").write_bytes(b"a,b\n1,2\n")
    r = jobs.run_daily(settings, staffed, date(2026, 11, 18), trigger="TEST", actor="tester")
    assert r["status"] == "SUCCESS" and sorted(r["processed"]) == ["Attendancereport.csv", "EOD.csv"] and r["send"] == "waiting for approval"
    assert not (inbox / "Attendancereport.csv").exists() and (inbox / "notes.csv").exists()     # Bizom files deleted after use
    assert jobs.run_daily(settings, staffed, date(2026, 11, 18), trigger="TEST", actor="tester")["status"] == "SUCCESS"   # rerun is safe
    assert jobs.run_daily(settings, staffed, date(2026, 11, 17), trigger="TEST", actor="tester")["status"] == "FAILED"    # nothing for that day
    (inbox / "Attendancereport.csv").write_bytes(attendance_csv("2026-11-19"))
    jobs.run_daily(settings, staffed, date(2026, 11, 19), trigger="TEST", actor="tester")
    with session_scope(staffed) as s:
        assert [h["status"] for h in jobs.history(s)][:4] == ["SUCCESS", "FAILED", "SUCCESS", "SUCCESS"]
        rep = reports.attendance_report(s, date(2026, 11, 1), date(2026, 11, 30))
        assert rep["days_uploaded"] == 2 and rep["totals"]["person_days"] == 18
        assert len(reports.attendance_report(s, date(2026, 11, 1), date(2026, 11, 30), q="asha")["people"]) == 1
        load_workbook(io.BytesIO(reports.report_excel(rep)))
        emp = reports.employee_report(s, "SL00003", date(2026, 11, 1), date(2026, 11, 30))
        assert emp["summary"]["days"] == 2 and emp["days"][0]["warnings"] and emp["summary"]["flagged_days"] == 2
        with pytest.raises(reports.ReportError):
            reports.attendance_report(s, date(2026, 11, 30), date(2026, 11, 1))
        daily_before = len(mail.items_for(s, date(2026, 11, 30)))
    g = monthly.generate(settings, staffed, "2026-11", trigger="TEST", actor="tester")
    assert g["status"] == "SUCCESS" and g["days"] == 2
    with session_scope(staffed) as s:
        items = {i.recipient_key: i for i in monthly.items(s, "2026-11")}
        assert set(items) == {f"MONTHLY:{k}" for k in ("ravi@example.com", "zonal1@example.com", "zonal2@example.com", "hod1@example.com", "DIRECTOR", "HR")}
        assert len(mail.items_for(s, date(2026, 11, 30))) == daily_before                      # month-end kept out of the daily list
        html, text, files = mail.render(s, items["MONTHLY:ravi@example.com"])
        assert "November 2026" in html and "Dear Ravi Manager" in html and "Ravi Manager" in text
        assert "fraud" not in html.lower() and "9999999999" not in html + files[1].content.decode()
        mnames = load_workbook(io.BytesIO(files[0].content)).sheetnames
        assert mnames[0] == "Summary" and {"Day by day", "Weeks", "Needs a conversation", "People", "Calendar"} <= set(mnames)
        assert "Teams" in load_workbook(io.BytesIO(mail.render(s, items["MONTHLY:DIRECTOR"])[2][0].content)).sheetnames
        done = mail.send_items(s, [i for i in items.values() if i.status == "PENDING"], "tester", settings.storage.area("sales_outbox"))
        assert {i.status for i in done} == {"SAVED"}
        log = reports.email_log(s)
        assert {e["kind"] for e in log} == {"Month-end"} and len(log) == len(done)
    g2 = monthly.generate(settings, staffed, "2026-11", trigger="TEST", actor="tester")           # again: no double send
    with session_scope(staffed) as s:
        assert {i.status for i in monthly.items(s, "2026-11") if i.recipient_key.startswith("MONTHLY:ravi")} >= {"SAVED", "DUPLICATE"}
    assert g2["emails"].get("PENDING", 0) == 0
    assert monthly.generate(settings, staffed, "2026-10", trigger="TEST", actor="tester")["status"] == "FAILED"


def test_new_sales_api_routes(staffed, settings, tmp_path):
    with TestClient(create_app(settings, staffed, frontend_dist=tmp_path / "x")) as api:
        api.post("/api/v1/sales/upload", headers=H, files=[("files", ("Attendancereport.csv", attendance_csv(), "text/csv"))])
        assert api.post("/api/v1/sales/staff", headers=H, json={"code": "SL04650", "name": "New Person"}).status_code == 200
        assert api.post("/api/v1/sales/staff", headers=H, json={"code": "SL04650", "name": "X"}).status_code == 422
        assert api.put("/api/v1/sales/staff/SL04650", headers=H, json={"zone": "GTR09"}).json()["zone"] == "GTR09"
        assert api.put("/api/v1/sales/staff/SL99999", headers=H, json={"zone": "x"}).status_code == 404
        rep = api.get("/api/v1/sales/reports/attendance").json()
        assert rep["to"] == D and rep["days_uploaded"] == 1
        assert api.get("/api/v1/sales/reports/attendance?start=2026-11-20&end=2026-11-01").status_code == 422
        assert api.get("/api/v1/sales/reports/attendance/excel").status_code == 200
        assert api.get("/api/v1/sales/reports/employee/SL00001").json()["summary"]["days"] == 1
        assert api.get("/api/v1/sales/reports/employee/XX00000").status_code == 404
        j = api.get("/api/v1/sales/jobs").json()
        assert j["inbox"].endswith("sales_inbox") and j["auto_send"] is False
        assert api.post("/api/v1/sales/jobs/daily", headers=H, json={"day": "2026-11-17"}).json()["status"] == "FAILED"
        assert api.get("/api/v1/sales/monthly").json()["months"][0]["month"] == "2026-11"
        assert api.post("/api/v1/sales/monthly/generate", headers=H, json={"month": "2026-10"}).status_code == 422
        g = api.post("/api/v1/sales/monthly/generate", headers=H, json={"month": "2026-11"}).json()
        assert len(g["items"]) == 6
        mid = next(i["id"] for i in g["items"] if i["status"] == "PENDING")
        assert "Monthly Field Sales" in api.get(f"/api/v1/sales/mail/{mid}/preview").text
        assert api.post("/api/v1/sales/monthly/2026-11/approve", headers=H, json={}).json()["sent_now"] == 4
        assert {e["kind"] for e in api.get("/api/v1/sales/emails").json()} == {"Month-end"}
        assert api.get("/api/v1/sales/monthly/2026-13").status_code == 422


def test_two_calls_at_the_same_time_one_without_location():
    """Real 23-Nov-2026 export: same start and end time, only one call had a location -> sorting must not crash."""
    head = ["Zone", "Call_ID", "User_Name", "EMP_Id", "Call_Start_Date", "Call_Start_Time", "Call_End_Time", "Total_Time_Spent",
            "Call_Status", "Order_Type", "Reason_Category_Name", "Distance_Variance(Mtrs)", "Call_Latitude", "Call_Longitude", "Order_Value",
            "Outlet_Mobile_No"]
    rows = [["GTR01", "1", "SL00001", "SL00001", D, "10:00:00", "10:00:20", "0:0:20", "PC", "Normal", "", "20", "", "", "", "9"],
            ["GTR01", "2", "SL00001", "SL00001", D, "10:00:00", "10:00:20", "0:0:20", "PC", "Normal", "", "20", "28.61", "77.21", "", "9"]]
    c = bizom.parse(bizom.read_rows(csv_bytes(head, rows), "c.csv"))
    assert c.calls["SL00001"].calls == 2 and c.calls["SL00001"].first_call


def test_testing_sends_only_to_the_testers_with_cc(staffed, settings, monkeypatch):
    """Testing on: every Field Sales email really goes only to the test recipient (To) + test CC, marked [TEST]."""
    from types import SimpleNamespace

    sent = []

    def fake_send(cfg, msg, outbox):
        sent.append((cfg.mode, msg))
        return SimpleNamespace(status="SENT", outbox_file=None)

    monkeypatch.setattr(mail, "send", fake_send)
    with session_scope(staffed) as s:
        save_email(s, SalesEmail(mode="test", test_recipient="tester@example.com", test_cc=["cc@example.com"],
                                 pilot_live=["ravi@example.com"]), "tester")
        up = service.process(s, [("a.csv", attendance_csv()), ("e.csv", eod_csv()), ("c.csv", calls_csv())], "tester")
        items = [i for i in mail.items_for(s, up.report_date) if i.status == "PENDING"]
        assert any(i.recipient_key == "DIRECTOR" for i in items)                     # held for no address -> goes to the testers
        done = mail.send_items(s, items, "tester", settings.storage.area("sales_outbox"))
        assert done and all(i.status == "TEST_SENT" and "tester@example.com (CC cc@example.com)" in i.note for i in done)
        assert all(mode == "live" and m["To"] == "tester@example.com" and m["Cc"] == "cc@example.com" and m["Subject"].startswith("[TEST] ")
                   and not m["Bcc"] for mode, m in sent)
        ravi = next(m for _, m in sent if "ravi@example.com" in m.get_body(("html",)).get_content())   # pilot too: only the testers
        assert ravi["To"] == "tester@example.com"
