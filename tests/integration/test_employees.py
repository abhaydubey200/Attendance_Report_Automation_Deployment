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
from daily.render import email_parts, scope_label
from database.connection import session_scope
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


def test_attendance_uses_master_and_each_hod_gets_own_people(engine, settings):
    with session_scope(engine) as s:
        _import(s)
        emp.mark_left(s, "E7", date(2026, 11, 12), "tester")       # left before the report date -> dropped
        up, outcomes = service.upload_and_send(s, settings, "summary.xlsx", summary_file(CASES), "tester")
        ins = json.loads(up.insights)
        rows = service.rows_for(s, up.upload_id)
    assert ins["master"] == {"matched": 7, "not_in_master": 1, "left_excluded": 1, "missing_from_file": 0}
    assert ins["excluded"] == 2                                     # 'test' + the leaver
    assert {h["name"] for h in ins["hods"]} == {"Asha Rao", "Vikram Shah", "Meera Iyer"}
    assert ins["scopes"]["HOD:Vikram Shah"]["summary"]["employees"] == 3
    assert ins["scopes"]["ALL"]["breakdown"]["by"] == "Department"
    assert any("not in the employee master" in h["text"] for h in ins["scopes"]["ALL"]["highlights"])
    by_code = {r["code"]: r for r in rows}
    assert by_code["E3"]["hod"] == "Vikram Shah" and by_code["E3"]["team"] == "lead.two" and "E7" not in by_code

    status = {o.scope: (o.status, o.recipients) for o in outcomes}
    assert status["ALL"][0] == "NO_RECIPIENTS"                       # no HR recipients configured in this test
    assert status["HOD:Vikram Shah"] == ("SAVED", ["vikram@example.com"])
    assert status["HOD:Meera Iyer"] == ("SAVED", ["meera@example.com", "meera.iyer@example.com"])
    outbox = sorted((settings.storage.area("outbox") / "2026-11-13").glob("*.eml"))
    msgs = [email.message_from_bytes(p.read_bytes()) for p in outbox]
    vikram = next(m for m in msgs if "vikram@example.com" in m["To"])
    assert "HOD Vikram Shah" in vikram["Subject"]
    xlsx = next(p for p in vikram.walk() if (p.get_filename() or "").endswith(".xlsx")).get_payload(decode=True)
    sheet = load_workbook(io.BytesIO(xlsx))["All Employees"]
    codes = {sheet.cell(r, 1).value for r in range(2, sheet.max_row + 1)}
    assert codes == {"E3", "E4", "E5"}                              # only Vikram's people


def test_hod_emails_can_be_switched_off(engine, settings):
    from core.config import EmailSettings
    from daily.settings_store import save_email_settings

    with session_scope(engine) as s:
        _import(s)
        save_email_settings(s, EmailSettings(send_to_hods=False, wait_for_bizom=False), "tester")
        _, outcomes = service.upload_and_send(s, settings, "summary.xlsx", summary_file(CASES), "tester")
    assert [o.scope for o in outcomes] == ["ALL"]


def test_scope_label_and_email_breakdown(engine, settings):
    assert scope_label("HOD:Asha Rao") == "HOD Asha Rao"
    with session_scope(engine) as s:
        _import(s)
        up = service.process_upload(s, settings, "summary.xlsx", summary_file(CASES), "tester")
        ins = json.loads(up.insights)
    _, html, _ = email_parts("APIS", DAY, "ALL", ins, "%d-%b-%Y", "X", ["HR"], None)
    assert "By department" in html and "Vikram Shah" in html


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
