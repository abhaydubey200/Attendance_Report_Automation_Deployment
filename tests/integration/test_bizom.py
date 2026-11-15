"""Bizom + Pocket HRMS merged by EMP_CODE. Synthetic data only."""

from __future__ import annotations

import json
from datetime import date

import pytest
from fastapi.testclient import TestClient

from api.main import CSRF_HEADER, create_app
from core.config import EmailSettings, Rules
from daily import analysis, bizom, service
from daily.analysis import FileError
from daily.settings_store import replace_recipients, save_email_settings
from database.connection import session_scope
from demo.synthetic import build_bizom_csv
from tests.integration.test_daily import CASES, summary_file

H = {CSRF_HEADER: "1"}
HEAD = ("Zone,SubzoneName,Name,User_Name,User_Id,Employee_Id,Role_id,DOJ,HQ,Designation,User_Status,Inactive_Date,Imei,"
        "Date_{d}_Attendance_Status,P,SL,PL,Leave,WO,Total_Month_Days,Presence%,Total_Leave")


def bizom_file(rows: list[tuple], d: str = "13-11-2026") -> bytes:
    """rows of (user_name, employee_id, status[, user_status, inactive_date])"""
    out = ["﻿" + HEAD.format(d=d)]
    for i, r in enumerate(rows):
        user, emp_id, status = r[:3]
        active, inactive = (r[3], r[4]) if len(r) > 3 else ("Active", "")
        out.append(f"Z1,SUB,{user.upper()} NAME,{user},{i},{emp_id},7,2024-01-01,HQ{i},SO,{active},{inactive},deadbeef{i},{status},1,0,,0,0,30,3.33,0")
    return ("\n".join(out) + "\n").encode("utf-8")


BIZOM = [
    ("E1", "E1", "A"),          # punched in HRMS -> punch wins (stays present)
    ("E5", "E5", "P"),          # HRMS absent (shift, no punch) -> present via Bizom
    ("E6@MT", "E6", "P"),       # HRMS not tracked -> present via Bizom; Employee_Id is the code
    ("E7", "E7", "P"),          # HRMS leave, Bizom present -> present in either
    ("E8", "E8", "WO"),         # HRMS on duty -> stays on duty
    ("AP001", "AP001", "P"),    # promoter only in Bizom -> added
    ("AP002", "AP002", "WO"),   # promoter on week off -> added, not counted in %
    ("SL777", "SL777", "P"),    # Bizom only, not in master, not AP -> skipped
    ("Vacant_TSM", "", "A"),    # no Employee_Id -> skipped
    ("TestMT", "TEST", "P"),    # excluded test user
    ("AP003", "AP003", "P", "Inactive", "2026-11-01"),   # inactive before the date -> excluded
]


def test_parse_bizom():
    day = bizom.parse_rows([r.split(",") for r in bizom_file(BIZOM).decode("utf-8-sig").splitlines()])
    assert day.report_date == date(2026, 11, 13) and day.skipped_no_id == 1
    assert day.records["E6"].status == "P" and "E6@MT" not in day.records
    with pytest.raises(bizom.BizomError, match="one day"):
        two = [["Employee_Id", "User_Name", "Date_13-11-2026_Attendance_Status", "Date_14-11-2026_Attendance_Status"]]
        bizom.parse_rows(two)


def test_merge_rules():
    raw_day, results, _ = analysis.classify(_hrms_rows(), Rules(exclude_codes=["^test$"]))
    day = bizom.parse_rows([r.split(",") for r in bizom_file(BIZOM).decode("utf-8-sig").splitlines()])
    merged, stats = analysis.merge_bizom(results, day, raw_day, Rules(exclude_codes=["^test$"]), known_codes={"E1"})
    by = {r.code.upper(): r for r in merged}
    assert (by["E1"].status, by["E1"].source) == ("PRESENT", "HRMS+BIZOM")
    assert (by["E5"].status, by["E5"].source) == ("PRESENT", "BIZOM")
    assert (by["E6"].status, by["E6"].bizom_status) == ("PRESENT", "P")
    assert by["E7"].status == "PRESENT"
    assert by["E8"].status == "ON_DUTY"
    assert by["AP001"].status == "PRESENT" and by["AP002"].status == "WEEK_OFF" and by["AP001"].category == "Sales"
    assert "SL777" not in by and "AP003" not in by and "TEST" not in by
    assert stats == {"rows": 10, "matched": 5, "decided": 3, "added": 2, "skipped": 2, "excluded": 2}
    s = analysis.summarize(merged, Rules())
    assert s["counts"]["WEEK_OFF"] == 1 and s["tracked"] == len(merged) - 1 - s["counts"]["NOT_TRACKED"]


def _hrms_rows():
    from ingestion.file_reader import read_raw
    from ingestion.reshapers import reshape_attendance_summary

    raw, sheets = read_raw(summary_file(CASES), "xlsx")
    return reshape_attendance_summary(raw, 1, sheets).rows


def test_upload_waits_for_bizom_then_sends(engine, settings):
    with session_scope(engine) as s:
        save_email_settings(s, EmailSettings(), "tester")                     # default: wait for both files
        replace_recipients(s, [{"name": "HR", "email": "hr@example.com", "scope": "ALL"}])
        up, outcomes, note = service.upload_files_and_send(s, settings, [("summary.xlsx", summary_file(CASES))], "tester")
        assert outcomes is None and "Waiting for the Bizom file" in note
        assert json.loads(up.insights)["scopes"]["ALL"]["summary"]["counts"]["NOT_TRACKED"] == 1
        up2, outcomes, note = service.upload_files_and_send(s, settings, [("bizom.csv", bizom_file(BIZOM))], "tester")
        assert note is None and [o.status for o in outcomes] == ["SAVED"]
        assert up2.original_filename == "summary.xlsx" and up2.bizom_filename == "bizom.csv"   # HRMS kept, Bizom added
        ins = json.loads(up2.insights)
        assert ins["sources"]["bizom"]["decided"] == 3
        assert ins["scopes"]["ALL"]["summary"]["counts"]["NOT_TRACKED"] == 0
        assert any(h["text"].startswith("Bizom:") for h in ins["scopes"]["ALL"]["highlights"])
        rows = {r["code"]: r for r in service.rows_for(s, up2.upload_id)}
        assert rows["E6"]["source"] == "BIZOM" and rows["AP001"]["status"] == "PRESENT"
        with pytest.raises(service.AlreadyUploaded, match="Bizom file"):
            service.process_files(s, settings, [("bizom.csv", bizom_file(BIZOM))], "tester")
        again = service.recalculate(s, settings, date(2026, 11, 13), "tester")
        assert again.bizom_filename == "bizom.csv" and again.employees == up2.employees


def test_bizom_only_day_and_date_mismatch(engine, settings):
    with session_scope(engine) as s:
        up = service.process_files(s, settings, [("b.csv", bizom_file([("AP001", "AP001", "P"), ("AP002", "AP002", "A")]))], "tester")
        assert up.employees == 2 and up.original_filename is None
        with pytest.raises(FileError, match="different dates"):
            service.process_files(s, settings, [("s.xlsx", summary_file(CASES)), ("b.csv", bizom_file(BIZOM, d="14-11-2026"))], "tester")


@pytest.fixture
def api(settings, engine, tmp_path):
    with TestClient(create_app(settings, engine, frontend_dist=tmp_path / "x")) as c:
        yield c


def test_two_files_in_one_upload_over_http(api):
    r = api.post("/api/v1/days/upload", headers=H, files=[
        ("files", ("AttendanceSummary.xlsx", summary_file(CASES), "application/octet-stream")),
        ("files", ("Bizom.csv", build_bizom_csv(date(2026, 11, 13)), "text/csv"))])
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["file"] == "AttendanceSummary.xlsx" and body["bizom_file"] == "Bizom.csv"
    days = api.get("/api/v1/days").json()
    assert days[0]["has_hrms"] and days[0]["has_bizom"]
    r = api.post("/api/v1/days/upload", headers=H, files=[("files", ("a.xlsx", summary_file(CASES))), ("files", ("b.xlsx", summary_file(CASES)))])
    assert r.status_code == 422 and "one Pocket HRMS file" in r.json()["detail"]
