"""Date-range reports: one employee, and many employees by filter. Synthetic data only."""

from __future__ import annotations

import io
from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient
from openpyxl import load_workbook

from api.main import CSRF_HEADER, create_app
from daily import employees as emp
from daily import service
from database.connection import session_scope
from demo.synthetic import build_master_xlsx, build_permission_xlsx, build_summary_xlsx

H = {CSRF_HEADER: "1"}
END = date(2026, 11, 13)


@pytest.fixture
def api(settings, engine, tmp_path):
    with session_scope(engine) as s:
        emp.import_rows(s, emp.read_master_file("m.xlsx", build_master_xlsx()), "tester")
        for i in range(3):
            d = END - timedelta(days=2 - i)
            service.process_files(s, settings, [("s.xlsx", build_summary_xlsx(d)), ("p.xlsx", build_permission_xlsx(d))], "tester")
    with TestClient(create_app(settings, engine, frontend_dist=tmp_path / "x")) as c:
        yield c


def test_employee_report(api):
    r = api.get("/api/v1/reports/employee/rk90000", params={"from": "2026-11-11", "to": "2026-11-13"})
    assert r.status_code == 200
    body = r.json()
    assert body["employee"]["code"] == "RK90000" and body["in_master"]
    assert [d["date"] for d in body["days"]] == ["2026-11-11", "2026-11-12", "2026-11-13"]
    assert body["summary"]["days"] == 3
    sales = api.get("/api/v1/reports/employee/SL90015", params={"from": "2026-11-11", "to": "2026-11-13"}).json()
    assert sales["in_master"] is False and sales["days"][0]["source"] == "HRMS"     # left out of the synthetic master
    assert api.get("/api/v1/reports/employee/NOPE1").status_code == 404
    x = api.get("/api/v1/reports/employee/RK90000/excel", params={"from": "2026-11-11", "to": "2026-11-13"})
    assert x.status_code == 200 and load_workbook(io.BytesIO(x.content))["Daily"].max_row == 4


def test_attendance_report_filters_and_excel(api):
    base = {"from": "2026-11-11", "to": "2026-11-13"}
    all_ = api.get("/api/v1/reports/attendance", params=base).json()
    assert all_["dates"] == ["2026-11-11", "2026-11-12", "2026-11-13"] and all_["totals"]["employees"] == 42
    assert "Mohan Synth" in all_["options"]["hod"] and all_["options"]["source"] == ["HRMS"]
    mohan = api.get("/api/v1/reports/attendance", params={**base, "hod": "Mohan Synth", "days": "true"}).json()
    assert mohan["totals"]["employees"] == 12 and {p["hod"] for p in mohan["employees"]} == {"Mohan Synth"}
    assert len(mohan["days"]) == 36
    absent = api.get("/api/v1/reports/attendance", params={**base, "status": "ABSENT", "days": "true"}).json()
    assert absent["employees"] and all(d["status"] == "ABSENT" for d in absent["days"])
    assert api.get("/api/v1/reports/attendance", params={"from": "2026-11-13", "to": "2026-11-01"}).status_code == 422
    x = api.get("/api/v1/reports/attendance/excel", params={**base, "hod": "Mohan Synth"})
    wb = load_workbook(io.BytesIO(x.content))
    assert wb["Summary"].max_row == 4 + 12 - 1 + 1 and "HOD: Mohan Synth" in wb["Summary"].cell(3, 1).value
    assert wb["Daily"].max_row == 37
    # Default range = the 30 days up to the latest upload.
    assert api.get("/api/v1/reports/attendance").json()["to"] == "2026-11-13"
