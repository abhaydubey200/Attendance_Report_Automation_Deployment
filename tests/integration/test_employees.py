"""Employee master: import (add + update only), CRUD, mark Left / restore, and HOD report routing.
Synthetic data only (example.com addresses)."""

from __future__ import annotations

import email
import io
import json
from datetime import date

import pytest
from fastapi.testclient import TestClient
from openpyxl import Workbook, load_workbook

from api.main import CSRF_HEADER, create_app
from daily import employees as emp
from daily import service
from daily.render import scope_label
from database.connection import session_scope
from database.models.daily import Employee
from tests.integration.test_daily import CASES, summary_file

H = {CSRF_HEADER: "1"}
DAY = date(2026, 11, 13)


def master_file(rows: list[list]) -> bytes:
    """Same layout as HR's EmployeeAmmendmentImport: blank first row, header on row 2, NBSP in a header."""
    wb = Workbook()
    ws = wb.active
    ws.append([])
    ws.append(["", "EMPLOYEE CODE", "Employee Name", "Department", "DOJ", "HOD", "Email ID - HOD", "Sub split ID",
               "Reporting Manager\xa0"])
    for i, r in enumerate(rows, start=1):
        ws.append([i, *r])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


MASTER = [
    ["E1", "Present OnTime", "Accounts", "2020-01-15", "ASHA RAO", "asha.rao@example.com", "lead.one@example.com", "Ravi"],
    ["E2", "Late Arrival", "Accounts", "", "Asha Rao", "asha.rao@example.com", "", "Ravi"],
    ["e3", "Left Early", "Production", "2019-05-01", "Vikram Shah", "vikram@example.com", "lead.two@example.com", "NA"],
    ["E4", "One Punch", "Production", "", "VIKRAM SHAH", "vikram@example.com", "lead.two@example.com", ""],
    ["E5", "No Punch Shift", "Production", "", "Vikram Shah", "not-an-email", "", ""],
    ["E6", "No Punch NoShift", "Sales", "", "NA", "", "", ""],
    ["E7", "On Leave", "Sales", "", "Meera Iyer", "meera@example.com; meera.iyer@example.com", "", ""],
    ["E8", "On Duty", "Sales", "", "Meera Iyer", "meera@example.com; meera.iyer@example.com", "", ""],
]


def _import(s, rows=MASTER):
    return emp.import_rows(s, emp.read_master_file("master.xlsx", master_file(rows)), "tester")


def test_read_and_import_normalises(engine):
    with session_scope(engine) as s:
        res = _import(s)
        assert (res.added, res.updated, res.rows) == (8, 0, 8)
        assert any("E5" in p and "Invalid email" in p for p in res.problems)
        e3 = emp.get(s, "E3")                                   # code upper-cased
        assert e3.hod_name == "Vikram Shah" and e3.reporting_manager is None   # 'NA' -> blank
        assert emp.get(s, "E1").hod_name == emp.get(s, "E2").hod_name == "Asha Rao"   # one spelling per HOD
        assert emp.get(s, "E1").date_of_joining == date(2020, 1, 15)
        assert emp.get(s, "E6").hod_name is None
        assert emp.get(s, "E5").hod_email is None               # bad value dropped, row kept
        d = emp.hod_directory(s)
        assert d["Vikram Shah"] == ["vikram@example.com"]
        assert d["Meera Iyer"] == ["meera@example.com", "meera.iyer@example.com"]
        assert emp.team_of("lead.one@example.com") == "lead.one" and emp.team_of(None) == emp.DIRECT


def test_reimport_adds_and_updates_never_removes(engine):
    with session_scope(engine) as s:
        _import(s)
        emp.mark_left(s, "E8", date(2026, 10, 31), "tester")
        changed = [r[:] for r in MASTER[1:]]                    # E1 missing from the new file
        changed[0][2] = "Finance"                               # E2 changes department
        changed.append(["E9", "New Joiner", "Sales", "", "Meera Iyer", "meera@example.com", "", ""])
        res = _import(s, changed)
        assert (res.added, res.updated, res.kept_left, res.not_in_file) == (1, 1, 1, 1)
        assert emp.get(s, "E1").status == emp.ACTIVE            # not removed
        assert emp.get(s, "E8").status == emp.LEFT              # stays Left
        assert emp.get(s, "E2").department == "Finance"
        hist = emp.history(s, "E2")
        assert hist[0]["action"] == "IMPORT_UPDATE" and hist[0]["changes"]["department"] == ["Accounts", "Finance"]


def test_create_update_left_restore(engine):
    with session_scope(engine) as s:
        _import(s)
        e = emp.create(s, {"code": "x10", "name": "Neha", "department": "accounts", "hod_name": "asha rao"}, "hr")
        assert (e.code, e.department, e.hod_name, e.hod_email) == ("X10", "Accounts", "Asha Rao", "asha.rao@example.com")
        with pytest.raises(emp.EmployeeError, match="already exists"):
            emp.create(s, {"code": "X10", "name": "Dup"}, "hr")
        with pytest.raises(emp.EmployeeError, match="name is required"):
            emp.create(s, {"code": "X11"}, "hr")
        emp.update(s, "X10", {"hod_name": "Vikram Shah"}, "hr")
        assert emp.get(s, "X10").hod_email == "vikram@example.com"   # follows the new HOD
        with pytest.raises(emp.EmployeeError, match="Invalid email"):
            emp.update(s, "X10", {"team_lead_email": "nope"}, "hr")
        emp.mark_left(s, "X10", date(2026, 11, 1), "hr")
        assert emp.get(s, "X10").status == emp.LEFT
        emp.restore(s, "X10", "hr")
        e = emp.get(s, "X10")
        assert (e.status, e.exit_date) == (emp.ACTIVE, None)
        assert [h["action"] for h in emp.history(s, "X10")] == ["RESTORE", "LEFT", "UPDATE", "CREATE"]


def test_attendance_uses_master(engine, settings):
    with session_scope(engine) as s:
        _import(s)
        emp.mark_left(s, "E7", date(2026, 11, 12), "tester")       # left before the report date -> dropped
        up = service.process_upload(s, settings, "summary.xlsx", summary_file(CASES), "tester")
        ins = json.loads(up.insights)
        rows = service.rows_for(s, up.upload_id)
    assert ins["master"] == {"matched": 7, "not_in_master": 1, "left_excluded": 1, "missing_from_file": 0, "out_of_scope": 0}
    assert ins["excluded"] == 2                                     # 'test' + the leaver
    assert {h["name"] for h in ins["hods"]} == {"Asha Rao", "Vikram Shah", "Meera Iyer"}
    assert ins["scopes"]["HOD:Vikram Shah"]["summary"]["employees"] == 3
    assert ins["scopes"]["ALL"]["breakdown"]["by"] == "Department"
    by_code = {r["code"]: r for r in rows}
    assert by_code["E3"]["hod"] == "Vikram Shah" and by_code["E3"]["team"] == "lead.two" and "E7" not in by_code
    assert scope_label("HOD:Asha Rao") == "HOD Asha Rao"


def test_routing_workbook_columns_status_and_issue(engine):
    wb = master_file([])
    from openpyxl import Workbook
    book = Workbook()
    book.active.title = "Summary"
    ws = book.create_sheet("Employee_Master")
    ws.append(["Employee_Code", "Employee_Name", "Department", "DOJ", "Employee_Status", "HOD_Name", "HOD_Email", "Sub_Split_ID",
               "Report_To_Type", "Report_To_Email", "Reporting_Manager_Name", "Routing_Status", "Issues"])
    ws.append(["SL1", "ONE", "SALES", "2020-01-01", None, "ARUN MISHRA", "arun@example.com", "lead@example.com", "", "", "RAVI", "READY", None])
    ws.append(["SL2", "TWO", "SALES", "2020-01-01", "Inactive", "ARUN MISHRA", "arun@example.com", "", "", "", "", "READY", None])
    ws.append(["HO3", "THREE", "CS", "", None, "VIKAS", "vaibhav@example.com", "", "", "", "", "BLOCKED", "HOD_EMAIL_CONFLICT"])
    buf = io.BytesIO()
    book.save(buf)
    assert wb  # (the plain amendment layout still works: see the tests above)
    with session_scope(engine) as s:
        res = emp.import_rows(s, emp.read_master_file("routing.xlsx", buf.getvalue()), "tester")
        assert res.added == 3 and not res.problems
        assert emp.get(s, "SL1").hod_name == "Arun Mishra" and emp.get(s, "SL1").reporting_manager == "RAVI"
        assert emp.get(s, "SL2").status == emp.LEFT
        assert emp.get(s, "HO3").routing_issue == "HOD_EMAIL_CONFLICT"


# ------------------------------------------------------------------ over HTTP
@pytest.fixture
def api(settings, engine, tmp_path):
    with TestClient(create_app(settings, engine, frontend_dist=tmp_path / "x")) as c:
        yield c


def test_employee_api(api):
    r = api.post("/api/v1/employees/import", headers=H,
                 files={"file": ("master.xlsx", master_file(MASTER), "application/octet-stream")})
    assert r.status_code == 200 and r.json()["added"] == 8
    body = api.get("/api/v1/employees").json()
    assert body["summary"]["active"] == 8 and len(body["summary"]["hods"]) == 3
    r = api.post("/api/v1/employees", headers=H, json={"code": "N1", "name": "New Person", "department": "Sales",
                                                       "hod_name": "Meera Iyer"})
    assert r.status_code == 201 and r.json()["hod_email"].startswith("meera@")
    assert api.post("/api/v1/employees", headers=H, json={"code": "N1", "name": "Again"}).status_code == 422
    r = api.put("/api/v1/employees/n1", headers=H, json={"reporting_manager": "Ravi", "code": "HACK"})
    assert r.status_code == 200 and r.json()["code"] == "N1" and r.json()["reporting_manager"] == "Ravi"
    assert api.put("/api/v1/employees/ZZZ", headers=H, json={"name": "x"}).status_code == 404
    r = api.post("/api/v1/employees/N1/left", headers=H, json={"exit_date": "2026-11-10"})
    assert r.json()["status"] == "LEFT" and r.json()["exit_date"] == "2026-11-10"
    assert api.post("/api/v1/employees/N1/restore", headers=H).json()["status"] == "ACTIVE"
    assert len(api.get("/api/v1/employees/N1/history").json()) == 4
    x = api.get("/api/v1/employees/export")
    assert x.status_code == 200
    ws = load_workbook(io.BytesIO(x.content)).active
    assert ws.cell(1, 1).value == "EMPLOYEE CODE" and ws.max_row == 10
    # The export can be re-imported unchanged.
    r = api.post("/api/v1/employees/import", headers=H, files={"file": ("e.xlsx", x.content, "application/octet-stream")})
    assert r.json()["added"] == 0 and r.json()["updated"] == 0
    # CSRF header is required for changes.
    assert api.post("/api/v1/employees", json={"code": "N2", "name": "x"}).status_code == 403
    nav = [p["slug"] for p in api.get("/api/v1/auth/me").json()["navigation"]]
    assert "employees" in nav


def test_out_of_scope_field_sales(engine):
    """Field sales (category Sales) who are not in the employee master are left out; listed employees always count."""
    from daily import service
    from daily.analysis import EmployeeResult
    with session_scope(engine) as s:
        s.add(Employee(code="SL0001", name="Listed Sales", status="ACTIVE", hod_name="H", hod_email="h@example.com"))
        s.add(Employee(code="HO0001", name="Office", status="ACTIVE", hod_name="H", hod_email="h@example.com"))
        s.flush()
        mk = lambda code, cat: EmployeeResult(code=code, name=code, category=cat, shift="", in_time=None, out_time=None,  # noqa: E731
                                             punches=0, work_minutes=None, leave_type=None, day_portion=None, status="ABSENT")
        kept, match = service.apply_master(s, date(2026, 11, 13), [mk("SL0001", "Sales"), mk("SL9999", "Sales"),
                                                                  mk("HO0001", "Head Office"), mk("HO9999", "Head Office")],
                                           ["Sales"])
    assert [r.code for r in kept] == ["SL0001", "HO0001", "HO9999"]
    assert match["out_of_scope"] == 1 and match["not_in_master"] == 1


def test_two_hods_with_the_same_name_stay_apart(engine, settings):
    """Two Sunil Kumars (one in HO, one in RK): the email tells them apart - teams never merge, the email is never guessed."""
    from core.config import EmailSettings
    from daily import mail, routing

    with session_scope(engine) as s:
        for code, name, hod, mail_ in (("R1", "Ravi", "Sunil Kumar", "sunil.tomar@example.com"),
                                       ("R2", "Rita", "Sunil Kumar", "sunil.tomar@example.com"),
                                       ("H1", "Hari", "Sunil Kumar", "sunil.kumar@example.com"),
                                       ("A1", "Anu", "Asha Rao", "asha@example.com")):
            emp.create(s, {"code": code, "name": name, "hod_name": hod, "hod_email": mail_}, "hr")
        summ = emp.summary(s)
        assert summ["shared_hod_names"] == ["Sunil Kumar"]
        assert {h["label"] for h in summ["hods"]} == {"Asha Rao", "Sunil Kumar (sunil.kumar@example.com)", "Sunil Kumar (sunil.tomar@example.com)"}
        # picking the shared name without an email is refused instead of guessed
        with pytest.raises(emp.EmployeeError, match="Two or more HODs are called Sunil Kumar"):
            emp.create(s, {"code": "N1", "name": "New", "hod_name": "Sunil Kumar"}, "hr")
        with pytest.raises(emp.EmployeeError, match="Enter the HOD email"):
            emp.update(s, "A1", {"hod_name": "Sunil Kumar"}, "hr")
        emp.update(s, "A1", {"hod_name": "Sunil Kumar", "hod_email": "sunil.tomar@example.com"}, "hr")
        rs = {r.code: r for r in routing.routes(s)}
        assert rs["R1"].detail_to == rs["A1"].detail_to == "sunil.tomar@example.com" and rs["H1"].detail_to == "sunil.kumar@example.com"
        assert rs["R1"].hod == "Sunil Kumar (sunil.tomar@example.com)" and rs["R1"].hod_plain == "Sunil Kumar"
        recs = {r.key: r for r in routing.recipients(s, EmailSettings(), None, list(rs.values()))}
        assert recs["sunil.tomar@example.com"].name == recs["sunil.kumar@example.com"].name == "Sunil Kumar"   # greeting: plain name
        assert {x.code for x in recs["sunil.tomar@example.com"].team} == {"R1", "R2", "A1"}
        rows = [{"code": c, "hod": r.hod, "status": "PRESENT", "flags": [], "in_time": None, "out_time": None,
                 "late_minutes": 0, "early_minutes": 0} for c, r in rs.items()]
        teams = {t["name"]: t["people"] for t in mail.team_table(rows, lambda _: None)}
        assert teams == {"Sunil Kumar (sunil.tomar@example.com)": 3, "Sunil Kumar (sunil.kumar@example.com)": 1}
