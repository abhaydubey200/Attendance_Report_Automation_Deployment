"""The daily tool: read -> classify -> insights -> Excel / dashboard / email -> send. Synthetic data only."""

from __future__ import annotations

import email
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
from daily.render import dashboard_html, email_parts
from daily.settings_store import get_rules, replace_recipients, save_email_settings, save_rules
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


def test_email_parts():
    day, results, excluded = _classify()
    ins = analysis.build_insights(day, results, Rules(), excluded)
    subject, html, text = email_parts("APIS India Limited", day, "ALL", ins, "%d-%b-%Y", "APIS Daily Attendance", ["Asha"], None)
    assert subject == "APIS Daily Attendance | All employees | 13-Nov-2026 | Attendance 68.8%"
    assert "Dear Asha" in html and "By category" in html and "Highlights" in text
    _, html2, _ = email_parts("APIS India Limited", day, "Plant", ins, "%d-%b-%Y", "X", ["A", "B"], "http://intranet/att")
    assert "Dear Team" in html2 and "By category" not in html2 and "http://intranet/att" in html2


# ------------------------------------------------------------------ service
def test_upload_replace_recalculate_and_send(engine, settings):
    data = summary_file(CASES)
    with session_scope(engine) as s:
        replace_recipients(s, [{"name": "Plant Head", "email": "plant@example.com", "scope": "Plant"},
                               {"name": "HR", "email": "hr@example.com", "scope": "ALL"}])
        up, outcomes = service.upload_and_send(s, settings, "summary.xlsx", data, "tester")
        status = {o.scope: o.status for o in outcomes}
    assert status == {"ALL": "SAVED", "Plant": "SAVED"}   # categories without recipients are skipped
    outbox = list((settings.storage.area("outbox") / "2026-11-13").glob("*.eml"))
    assert len(outbox) == 2
    msg = email.message_from_bytes(outbox[0].read_bytes())
    names = sorted(p.get_filename() for p in msg.walk() if p.get_filename())
    assert any(n.endswith(".xlsx") for n in names) and any(n.endswith("_dashboard.html") for n in names)

    with session_scope(engine) as s, pytest.raises(service.AlreadyUploaded):
        service.process_upload(s, settings, "summary.xlsx", data, "tester")
    with session_scope(engine) as s:
        save_rules(s, Rules(late_after="11:00", exclude_codes=["^test$"]), "tester")
        up2 = service.recalculate(s, settings, DAY, "tester")
        assert json.loads(up2.insights)["scopes"]["ALL"]["summary"]["late"] == 0
        assert service.current_upload(s, DAY).upload_id == up2.upload_id


def test_live_mode_failure_is_logged_not_raised(engine, settings, monkeypatch):
    from core.config import EmailSettings

    with session_scope(engine) as s:
        replace_recipients(s, [{"name": "HR", "email": "hr@example.com", "scope": "ALL"}])
        save_email_settings(s, EmailSettings(mode="live", wait_for_bizom=False, smtp_host="127.0.0.1", smtp_port=9, sender="hr@example.com",
                                             smtp_starttls=False), "tester")
        up, outcomes = service.upload_and_send(s, settings, "summary.xlsx", summary_file(CASES), "tester")
    failed = [o for o in outcomes if o.scope == "ALL"][0]
    assert failed.status == "FAILED" and "Could not send" in failed.detail


def test_recipient_validation(engine):
    with session_scope(engine) as s:
        with pytest.raises(ValueError, match="Invalid email"):
            replace_recipients(s, [{"name": "x", "email": "not-an-email", "scope": "ALL"}])
        with pytest.raises(ValueError, match="Choose"):
            replace_recipients(s, [{"name": "x", "email": "a@b.co", "scope": ""}])


# ------------------------------------------------------------------ over HTTP
@pytest.fixture
def api(settings, engine, tmp_path):
    with TestClient(create_app(settings, engine, frontend_dist=tmp_path / "x")) as c:
        yield c


def test_full_flow_over_http(api):
    r = api.put("/api/v1/settings/recipients", headers=H, json={"recipients": [
        {"name": "Sales Mgr", "email": "sales@example.com", "scope": "Sales"}, {"name": "HR", "email": "hr@example.com", "scope": "ALL"}]})
    assert r.status_code == 200
    r = api.post("/api/v1/days/upload", headers=H, files={"file": ("AttendanceSummary.xlsx", summary_file(CASES))})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["report_date"] == "2026-11-13" and body["auto_sent"]
    assert {e["scope"]: e["status"] for e in body["email_results"]}["Sales"] == "SAVED"

    again = api.post("/api/v1/days/upload", headers=H, files={"file": ("AttendanceSummary.xlsx", summary_file(CASES))})
    assert again.status_code == 409 and "already uploaded" in again.json()["detail"]
    ok = api.post("/api/v1/days/upload", headers=H, data={"replace": "true"}, files={"file": ("A.xlsx", summary_file(CASES))})
    assert ok.status_code == 200

    days = api.get("/api/v1/days").json()
    assert days[0]["report_date"] == "2026-11-13" and days[0]["attendance_pct"] == 68.8
    day = api.get("/api/v1/days/2026-11-13").json()
    assert len(day["rows"]) == 9 and day["insights"]["scopes"]["ALL"]["highlights"]

    x = api.get("/api/v1/days/2026-11-13/excel", params={"scope": "Sales"})
    assert x.status_code == 200 and "Sales" in x.headers["content-disposition"]
    d = api.get("/api/v1/days/2026-11-13/dashboard")
    assert d.status_code == 200 and "attachment" in d.headers["content-disposition"] and "sandbox" in d.headers["content-security-policy"]
    p = api.get("/api/v1/days/2026-11-13/email-preview", params={"scope": "Sales"})
    assert "Dear Sales Mgr" in p.text and "sandbox" in p.headers["content-security-policy"]
    assert api.get("/api/v1/days/2026-11-13/excel", params={"scope": "Nope"}).status_code == 404

    sent = api.post("/api/v1/days/2026-11-13/send", headers=H, json={"scopes": ["ALL"]}).json()
    assert sent["mode"] == "test" and sent["email_results"][0]["status"] == "SAVED"
    log = api.get("/api/v1/emails").json()
    assert len(log) >= 3 and log[0]["scope"] == "ALL"

    bad = api.post("/api/v1/days/upload", headers=H, files={"file": ("x.csv", b"a,b\n1,2\n")})
    assert bad.status_code == 422 and "Attendance Summary" in bad.json()["detail"]


def test_settings_over_http(api):
    s = api.get("/api/v1/settings").json()
    assert s["rules"]["late_after"] == "09:30" and s["email"]["mode"] == "test" and s["smtp_password_set"] is False
    r = api.put("/api/v1/settings/rules", headers=H, json={**s["rules"], "late_after": "10:00"})
    assert r.status_code == 200 and api.get("/api/v1/settings").json()["rules"]["late_after"] == "10:00"
    assert api.put("/api/v1/settings/rules", headers=H, json={**s["rules"], "late_after": "ten"}).status_code == 422
    assert api.put("/api/v1/settings/email", headers=H, json={**s["email"], "mode": "live"}).status_code == 422
    ok = api.post("/api/v1/settings/test-email", headers=H, json={"to": "someone@example.com"}).json()
    assert ok == {"status": "SAVED", "mode": "test"}
