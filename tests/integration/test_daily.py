"""The daily tool: read -> classify -> insights -> Excel / dashboard / email -> send. Synthetic data only."""

from __future__ import annotations

import email
import email.policy
import io
import json
from datetime import date

import pytest
from fastapi.testclient import TestClient
from openpyxl import Workbook, load_workbook

from api.main import CSRF_HEADER, create_app
from core.config import Rules
from daily import analysis, service
from daily.analysis import FileError
from daily.render import dashboard_html
from daily.settings_store import get_rules, save_email_settings, save_rules
from database.connection import session_scope
from demo.synthetic import build_summary_xlsx
from ingestion.file_reader import ReadError, read_raw
from ingestion.reshapers import reshape_attendance_summary

DAY = date(2026, 11, 13)
H = {CSRF_HEADER: "1"}


def summary_file(rows: list[tuple], day: str = "13/11/2026") -> bytes:
    """Hand-made Attendance Summary: rows of (code, name, category, shift, [times], type, portion)."""
    wb = Workbook()
    ws = wb.active
    for line in (["Generated with Pocket HRMS"], ["Head Office : X"], ["AttendanceSummary"], ["Run Date", f"{day} 15:36"],
                 ["Code", "Name", "Category", "Date", "Shift Name", "In-Out Time", "Type", "Day", "Remarks"]):
        ws.append(line)
    for code, name, cat, shift, times, typ, portion in rows:
        t = list(times) + ["", ""]
        ws.append([code, name, cat, day, shift, t[0], typ, portion, ""])
        ws.append([code, name, cat, day, shift, t[1], typ, portion, ""])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


CASES = [
    ("E1", "Present OnTime", "Head Office", "General Shift", ["09:10", "18:30"], "", ""),
    ("E2", "Late Arrival", "Head Office", "General Shift", ["10:15", "19:00"], "", ""),
    ("E3", "Left Early", "Plant", "General Shift", ["09:00", "16:00"], "", ""),
    ("E4", "One Punch", "Plant", "General Shift", ["09:05"], "", ""),
    ("E5", "No Punch Shift", "Plant", "General Shift", [], "", ""),
    ("E6", "No Punch NoShift", "Sales", "Shift Not Assigned", [], "", ""),
    ("E7", "On Leave", "Sales", "Shift Not Assigned", [], "PL", "Full Day"),
    ("E8", "On Duty", "Sales", "General Shift", [], "LD", "Full Day"),
    ("E9", "Half Leave", "Sales", "General Shift", ["14:00", "18:30"], "SL", "Half Day"),
    ("test", "Test Account", "AONE", "Shift Not Assigned", [], "", ""),
]


def _classify(rows=CASES, rules=None):
    raw, _ = read_raw(summary_file(rows), "xlsx")
    return analysis.classify(reshape_attendance_summary(raw).rows, rules or Rules(exclude_codes=["^test$"]))


# ------------------------------------------------------------------ reading + classification
def test_reshaper_pairs_rows_and_drops_remarks():
    raw, _ = read_raw(build_summary_xlsx(DAY), "xlsx")
    t = reshape_attendance_summary(raw)
    assert len(t.rows) == 44 and "Remarks" not in t.columns
    with pytest.raises(ReadError, match="Header row not found"):
        reshape_attendance_summary([["a", "b"]])


def test_statuses_and_flags():
    day, results, excluded = _classify()
    by = {r.code: r for r in results}
    assert day == DAY and excluded == 1
    assert by["E1"].status == "PRESENT" and by["E1"].flags == [] and by["E1"].work_minutes == 560
    assert by["E2"].status == "PRESENT" and "LATE" in by["E2"].flags and by["E2"].late_minutes == 45
    assert "LEFT_EARLY" in by["E3"].flags and by["E3"].early_minutes == 120 and "SHORT_HOURS" in by["E3"].flags
    assert by["E4"].status == "MISSING_PUNCH"
    assert by["E5"].status == "ABSENT" and by["E6"].status == "NOT_TRACKED"
    assert by["E7"].status == "LEAVE" and by["E8"].status == "ON_DUTY" and by["E9"].status == "HALF_DAY"


def test_rules_change_the_outcome():
    rules = Rules(late_after="10:30", no_punch_no_shift="ABSENT", on_duty_codes=[], exclude_codes=[])
    _, results, excluded = _classify(rules=rules)
    by = {r.code: r for r in results}
    assert excluded == 0 and "LATE" not in by["E2"].flags
    assert by["E6"].status == "ABSENT" and by["E8"].status == "LEAVE"


def test_file_problems_are_reported_plainly(settings):
    with pytest.raises(FileError, match="one day at a time"):
        raw, _ = read_raw(summary_file(CASES[:1]) , "xlsx")
        rows = reshape_attendance_summary(raw).rows + [{**reshape_attendance_summary(raw).rows[0], "Date": "14/11/2026"}]
        analysis.classify(rows, Rules())
    with pytest.raises(FileError, match="Attendance Summary"):
        service.read_file(settings, "a.csv", b"name,value\nx,1\n")
    with pytest.raises(FileError, match="Unsupported"):
        service.read_file(settings, "a.exe", b"MZ")


# ------------------------------------------------------------------ insights
def test_insights_numbers_and_highlights():
    day, results, excluded = _classify()
    ins = analysis.build_insights(day, results, Rules(), excluded)
    s = ins["scopes"]["ALL"]["summary"]
    assert s["employees"] == 9 and s["tracked"] == 8
    # present-equivalent = PRESENT 3 + ON_DUTY 1 + MISSING_PUNCH 1 + 0.5 HALF_DAY = 5.5 of 8
    assert s["attendance_pct"] == 68.8 and s["counts"]["ABSENT"] == 1 and s["late"] == 1
    texts = " ".join(h["text"] for h in ins["scopes"]["ALL"]["highlights"])
    assert "Attendance 68.8% of 8 tracked" in texts and "1 late arrivals after 09:30" in texts
    assert "not tracked" in texts and "missing punch" in texts
    assert set(ins["categories"]) == {"Head Office", "Plant", "Sales"}
    assert ins["scopes"]["Plant"]["summary"]["employees"] == 3


def test_previous_day_comparison():
    day, results, excluded = _classify()
    prev = analysis.build_insights(date(2026, 11, 12), results[:3], Rules(), 0)
    ins = analysis.build_insights(day, results, Rules(), excluded, prev)
    assert "from previous day" in ins["scopes"]["ALL"]["highlights"][0]["text"]


# ------------------------------------------------------------------ outputs
def _rows(results):
    return [analysis.result_to_dict(r) for r in results]


def test_excel_report_sheets_and_scope():
    from daily.excel_report import build_excel

    day, results, excluded = _classify()
    ins = analysis.build_insights(day, results, Rules(), excluded)
    wb = load_workbook(io.BytesIO(build_excel("APIS India Limited", day, "Plant", ins, _rows(results), "%d-%b-%Y")))
    assert wb.sheetnames == ["Summary", "All Employees", "Absent", "Late Arrivals", "Left Early", "Missing Punch",
                             "Leave, On Duty, Week Off", "Short Hours", "Not Tracked"]
    codes = {row[0].value for row in wb["All Employees"].iter_rows(min_row=2)}
    assert codes == {"E3", "E4", "E5"}                                     # Plant only
    assert wb["Absent"]["A2"].value == "E5"


def test_dashboard_embeds_data_safely():
    day, results, excluded = _classify()
    results[0].name = "</script><script>alert(1)</script>"
    ins = analysis.build_insights(day, results, Rules(), excluded)
    html = dashboard_html("APIS India Limited", day, "ALL", ins, _rows(results), "%d-%b-%Y").decode()
    assert "</script><script>alert(1)" not in html and "\\u003c/script\\u003e" in html
    assert '"attendance_pct": 68.8' in html


# ------------------------------------------------------------------ service
def test_upload_replace_recalculate_and_send(engine, settings):
    """No employee master yet: nobody can be routed, so only the Director (company summary) and the HR
    exception email are planned - and sent at once because approval is off in these tests."""
    data = summary_file(CASES)
    with session_scope(engine) as s:
        up, items = service.upload_and_send(s, settings, "summary.xlsx", data, "tester")
        status = {i.recipient_key: i.status for i in items}
    assert status == {"DIRECTOR": "SAVED", "HR": "SAVED"}
    outbox = list((settings.storage.area("outbox") / "2026-11-13").glob("*.eml"))
    assert len(outbox) == 2
    msg = email.message_from_bytes(next(p for p in outbox if b"hr@example.com" in p.read_bytes()).read_bytes(),
                                   policy=email.policy.default)
    assert "NOT_IN_EMPLOYEE_MASTER" in msg.get_body(("html",)).get_content()

    with session_scope(engine) as s, pytest.raises(service.AlreadyUploaded):
        service.process_upload(s, settings, "summary.xlsx", data, "tester")
    with session_scope(engine) as s:
        save_rules(s, Rules(late_after="11:00", exclude_codes=["^test$"]), "tester")
        up2 = service.recalculate(s, settings, DAY, "tester")
        assert json.loads(up2.insights)["scopes"]["ALL"]["summary"]["late"] == 0
        assert service.current_upload(s, DAY).upload_id == up2.upload_id


def test_live_mode_failure_is_retried_and_logged(engine, settings, monkeypatch):
    from core.config import EmailSettings
    from daily import mail

    naps = []
    monkeypatch.setattr(mail, "SLEEP", naps.append)
    with session_scope(engine) as s:
        save_email_settings(s, EmailSettings(mode="live", provider="smtp", wait_for_bizom=False, approval_required=False, smtp_host="127.0.0.1",
                                             smtp_port=9, sender="attendance@example.com", smtp_starttls=False,
                                             director_emails=["director@example.com"], hr_emails=["hr@example.com"]), "tester")
        up, items = service.upload_and_send(s, settings, "summary.xlsx", summary_file(CASES), "tester")
        failed = [i for i in items if i.recipient_key == "DIRECTOR"][0]
        assert failed.status == "FAILED" and "Could not send" in failed.note and failed.attempts == 3
    assert naps == [2, 4, 2, 4]          # two emails, back-off between the 3 attempts of each


# ------------------------------------------------------------------ over HTTP
@pytest.fixture
def api(settings, engine, tmp_path):
    with TestClient(create_app(settings, engine, frontend_dist=tmp_path / "x")) as c:
        yield c


def test_full_flow_over_http(api):
    r = api.post("/api/v1/days/upload", headers=H, files={"file": ("AttendanceSummary.xlsx", summary_file(CASES))})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["report_date"] == "2026-11-13" and body["auto_sent"]
    assert {m["key"]: m["status"] for m in body["mail"]} == {"DIRECTOR": "SAVED", "HR": "SAVED"}

    again = api.post("/api/v1/days/upload", headers=H, files={"file": ("AttendanceSummary.xlsx", summary_file(CASES))})
    assert again.status_code == 409 and "already uploaded" in again.json()["detail"]
    ok = api.post("/api/v1/days/upload", headers=H, data={"replace": "true"}, files={"file": ("A.xlsx", summary_file(CASES))})
    assert ok.status_code == 200 and {m["status"] for m in ok.json()["mail"]} == {"DUPLICATE"}   # sent once per day

    days = api.get("/api/v1/days").json()
    assert days[0]["report_date"] == "2026-11-13" and days[0]["attendance_pct"] == 68.8
    day = api.get("/api/v1/days/2026-11-13").json()
    assert len(day["rows"]) == 9 and day["insights"]["scopes"]["ALL"]["highlights"]

    x = api.get("/api/v1/days/2026-11-13/excel", params={"scope": "Sales"})
    assert x.status_code == 200 and "Sales" in x.headers["content-disposition"]
    d = api.get("/api/v1/days/2026-11-13/dashboard")
    assert d.status_code == 200 and "attachment" in d.headers["content-disposition"] and "sandbox" in d.headers["content-security-policy"]
    assert api.get("/api/v1/days/2026-11-13/excel", params={"scope": "Nope"}).status_code == 404

    log = api.get("/api/v1/emails").json()
    assert len(log) == 2 and {e["scope"] for e in log} == {"DIRECTOR", "HR"}

    bad = api.post("/api/v1/days/upload", headers=H, files={"file": ("x.csv", b"a,b\n1,2\n")})
    assert bad.status_code == 422 and "Attendance Summary" in bad.json()["detail"]


def test_settings_over_http(api):
    s = api.get("/api/v1/settings").json()
    assert s["rules"]["late_after"] == "09:30" and s["email"]["mode"] == "test" and s["smtp_password_set"] is False
    assert s["secrets"]["GRAPH_CLIENT_SECRET"] is False
    r = api.put("/api/v1/settings/rules", headers=H, json={**s["rules"], "late_after": "10:00"})
    assert r.status_code == 200 and api.get("/api/v1/settings").json()["rules"]["late_after"] == "10:00"
    assert api.put("/api/v1/settings/rules", headers=H, json={**s["rules"], "late_after": "ten"}).status_code == 422
    assert api.put("/api/v1/settings/email", headers=H, json={**s["email"], "mode": "live"}).status_code == 422
    bad = api.put("/api/v1/settings/email", headers=H, json={**s["email"], "director_emails": ["not-an-email"]})
    assert bad.status_code == 422 and "Director" in bad.json()["detail"]
    good = api.put("/api/v1/settings/email", headers=H, json={**s["email"], "director_emails": [" MD@Example.com "]})
    assert good.json()["director_emails"] == ["md@example.com"]
    ok = api.post("/api/v1/settings/test-email", headers=H, json={"to": "someone@example.com"}).json()
    assert ok == {"status": "SAVED", "mode": "test"}
