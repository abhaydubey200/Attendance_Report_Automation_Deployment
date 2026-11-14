"""REST API for Phases 2-12: upload flow over HTTP, runs, analytics, exceptions, reports, AI, scoping."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from api.main import CSRF_HEADER, create_app
from tests.fixtures.synthetic import DAILY_ORDER, MASTER_ORDER, SCHEMAS, SOURCE_OF, build_dataset_files
from tests.integration.test_api import login, with_auth_mode
from tests.integration.test_ingestion import DAY

H = {CSRF_HEADER: "1"}


@pytest.fixture
def operator(settings, engine, tmp_path):
    """No-login mode: HR_ADMIN + SYSTEM_ADMIN local operator."""
    with TestClient(create_app(settings, engine, frontend_dist=tmp_path / "x")) as c:
        yield c


def define_schemas(c):
    for ds, schema in SCHEMAS.items():
        r = c.post(f"/api/v1/datasets/{ds}/schemas", json={"definition": schema.model_dump(), "notes": "synthetic"}, headers=H)
        assert r.status_code == 200, r.text


def upload(c, ds, name, data, supersede=True):
    r = c.post("/api/v1/uploads/inspect", headers=H, files={"file": (name, data, "text/csv")},
               data={"dataset_id": ds, "source_system": SOURCE_OF[ds], "reporting_date": DAY.isoformat(), "header_row": "1"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["can_confirm"], body
    r = c.post(f"/api/v1/uploads/{body['token']}/confirm", headers=H, json={"acknowledge_review": True, "supersede": supersede})
    assert r.status_code == 200, r.text
    return r.json()


def load_and_run(c):
    define_schemas(c)
    files = build_dataset_files(DAY)
    for ds in MASTER_ORDER + DAILY_ORDER:
        upload(c, ds, *files[ds])
    r = c.post("/api/v1/runs", json={"reporting_date": DAY.isoformat()}, headers=H)
    assert r.status_code == 200 and r.json()["state"] == "READY_FOR_REVIEW", r.text
    return r.json()["run_id"]


def test_end_to_end_over_http(operator):
    c = operator
    assert c.get("/api/v1/datasets").json()[0]["schema_status"] == "PENDING_DISCOVERY"
    run_id = load_and_run(c)
    assert {d["schema_status"] for d in c.get("/api/v1/datasets").json() if d["dataset_id"] in SCHEMAS} == {"DEFINED"}
    hist = c.get("/api/v1/uploads").json()
    assert len(hist) == 7 and hist[0]["status"] == "READY_FOR_PROCESSING"
    assert "row_number" in c.get(f"/api/v1/uploads/{hist[0]['upload_id']}/exceptions.csv").text

    dash = c.get("/api/v1/dashboard/summary", params={"date": DAY.isoformat()}).json()
    assert dash["run"]["run_id"] == run_id and dash["kpis"]["eligible_employees"] == 8
    assert dash["kpis"]["attendance_pct"] is None
    assert len(c.get("/api/v1/attendance/daily", params={"date": DAY.isoformat()}).json()) == 8
    assert c.get("/api/v1/attendance/employee/TEST-0001", params={"start": DAY.isoformat(), "end": DAY.isoformat()}).json()["rows"]
    assert c.get("/api/v1/attendance/trend", params={"start": "2026-01-01", "end": DAY.isoformat()}).status_code == 400
    assert c.get("/api/v1/data-quality", params={"start": DAY.isoformat(), "end": DAY.isoformat()}).json()["unmapped_employees"] == 4

    pending = c.get("/api/v1/mappings", params={"status_filter": "PENDING"}).json()
    bz1 = next(m for m in pending if m["source_employee_id"] == "BZ-01")
    assert bz1["suggested_employee"].startswith("TEST-0001")
    r = c.post(f"/api/v1/mappings/{bz1['mapping_id']}/resolve", json={"employee_key": bz1["suggested_employee_key"]}, headers=H)
    assert r.json()["status"] == "VERIFIED"

    exc = c.get("/api/v1/exceptions", params={"status": "OPEN"}).json()
    e = exc[0]
    for action in ({"action": "ASSIGN"}, {"action": "START"},
                   {"action": "RESOLVE", "decision": "NO_CHANGE", "comment": "Checked; no change"}):
        r = c.post(f"/api/v1/exceptions/{e['exception_id']}/action", json=action, headers=H)
        assert r.status_code == 200, r.text
    assert [h["to"] for h in c.get(f"/api/v1/exceptions/{e['exception_id']}/history").json()][-1] == "RESOLVED"

    reps = c.get("/api/v1/reports", params={"run_id": run_id}).json()
    assert {r["report_type"] for r in reps} == {"HOD", "DIRECTORS", "HR_ADMIN"}
    html = next(r for r in reps if r["file_format"] == "HTML")
    d = c.get(f"/api/v1/reports/{html['report_id']}/download", params={"inline": True})
    assert d.status_code == 200 and "sandbox" in d.headers["content-security-policy"]
    assert c.post(f"/api/v1/runs/{run_id}/distribute", headers=H).status_code == 409
    assert c.post(f"/api/v1/runs/{run_id}/approve", headers=H).json()["state"] == "APPROVED"
    for r in reps:
        if r["file_format"] == "XLSX":
            assert c.post(f"/api/v1/reports/{r['report_id']}/decision", json={"decision": "APPROVED"}, headers=H).status_code == 200
    dist = c.post(f"/api/v1/runs/{run_id}/distribute", headers=H).json()
    assert dist["mode"] == "TEST" and dist["sent"] > 0

    detail = c.get(f"/api/v1/runs/{run_id}").json()
    assert detail["state"] == "COMPLETED" and detail["logs"]

    assert c.get("/api/v1/ai/status").json()["enabled"] is False
    ans = c.post("/api/v1/ai/ask", json={"question": "What was the overall attendance on 13-11-2026?"}, headers=H).json()
    assert "eligible" in ans["text"] and ans["period"] == DAY.isoformat()

    assert c.get("/api/v1/admin/rules").json()["is_approved"] is False
    assert c.get("/api/v1/admin/settings").json()["email"]["transport"] == "outbox"
    assert any(a["action"] == "UPLOAD_CONFIRM" for a in c.get("/api/v1/admin/audit").json())
    assert "lines" in c.get("/api/v1/system/logs").json()


def test_upload_rejections_over_http(operator):
    c = operator
    r = c.post("/api/v1/uploads/inspect", headers=H, files={"file": ("x.exe", b"MZ", "application/octet-stream")},
               data={"dataset_id": "HRMS_ATTENDANCE", "source_system": "POCKET_HRMS", "reporting_date": DAY.isoformat()})
    assert r.status_code == 200 and r.json()["accepted"] is False
    r = c.post("/api/v1/uploads/inspect", headers=H, files={"file": ("x.csv", b"a\n1", "text/csv")},
               data={"dataset_id": "HRMS_ATTENDANCE", "source_system": "BIZOM", "reporting_date": DAY.isoformat()})
    assert r.status_code == 400
    bad = c.post("/api/v1/datasets/HRMS_ATTENDANCE/schemas", json={"definition": {"columns": {"A": "nope"}}}, headers=H)
    assert bad.status_code == 422


def test_hod_scope_over_http(settings, engine, tmp_path, make_user):
    with TestClient(create_app(settings, engine, frontend_dist=tmp_path / "x")) as op:
        run_id = load_and_run(op)
    make_user("hod.fin", ["HOD"], departments=["FIN"])
    with TestClient(create_app(with_auth_mode(settings, "local"), engine, frontend_dist=tmp_path / "x")) as c:
        login(c, "hod.fin")
        assert c.get("/api/v1/dashboard/summary", params={"date": DAY.isoformat()}).json()["kpis"]["eligible_employees"] == 2
        assert {r["department_code"] for r in c.get("/api/v1/attendance/daily", params={"date": DAY.isoformat()}).json()} == {"FIN"}
        assert c.get("/api/v1/attendance/employee/TEST-0001",
                     params={"start": DAY.isoformat(), "end": DAY.isoformat()}).status_code == 404
        reps = c.get("/api/v1/reports", params={"run_id": run_id}).json()
        assert {(r["report_type"], r["department_code"]) for r in reps} == {("HOD", "FIN")}
        for path in ("/api/v1/uploads", "/api/v1/runs", "/api/v1/mappings", "/api/v1/exceptions", "/api/v1/admin/audit"):
            assert c.get(path).status_code == 403, path
        assert c.post("/api/v1/runs", json={"reporting_date": DAY.isoformat()}, headers=H).status_code == 403
