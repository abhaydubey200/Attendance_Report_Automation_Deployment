"""Per-recipient routing and the daily emails (build brief: APIS Daily Attendance Auto-Mailer).
Synthetic people, example.com addresses only."""

from __future__ import annotations

import email
import io
import json
import os
import time
from datetime import date

import httpx
import pytest
from fastapi.testclient import TestClient
from openpyxl import Workbook, load_workbook

from api.main import CSRF_HEADER, create_app
from core.config import EmailSettings
from daily import employees as emp
from daily import mail, mailer, routing, service
from daily.settings_store import get_email_settings, save_email_settings
from database.connection import session_scope
from tests.integration.test_daily import summary_file

H = {CSRF_HEADER: "1"}
DAY = date(2026, 11, 13)
# code, name, department, HOD, HOD email, Sub split ID, reporting manager, issue
MASTER = [
    ("T1", "Team One A", "SALES", "ARUN MISHRA", "arun@example.com", "lead.a@example.com", "LEAD A", None),
    ("T2", "Team One B", "SALES", "ARUN MISHRA", "arun@example.com", "lead.a@example.com", "LEAD A", None),
    ("T3", "Arun Direct", "SALES", "ARUN MISHRA", "arun@example.com", "arun@example.com", "ARUN MISHRA", None),
    ("T4", "No Sub Split", "PRODUCTION", "RAHUL SHARMA", "rahul@example.com", "", "RAHUL SHARMA", None),
    ("D1", "Director Staff", "DIRECTOR OFFICE", "", "", "", "", "NO_HOD_EMAIL"),
    ("C1", "Conflict Person", "COMPANY SECRETARIAL", "VIKAS", "arun@example.com", "", "VIKAS", "HOD_EMAIL_CONFLICT"),
]
ATTENDANCE = [  # code, name, category, shift, times, type, portion
    ("T1", "Team One A", "Sales", "General Shift", ["09:05", "18:30"], "", ""),
    ("T2", "Team One B", "Sales", "General Shift", [], "", ""),                    # absent -> attention
    ("T3", "Arun Direct", "Sales", "General Shift", ["10:20", "19:00"], "", ""),   # late -> attention
    ("T4", "No Sub Split", "Plant", "General Shift", [], "WFH", "Full Day"),
    ("D1", "Director Staff", "Head Office", "General Shift", ["09:00", "18:00"], "", ""),
    ("C1", "Conflict Person", "Head Office", "General Shift", ["09:00", "18:00"], "", ""),
    ("X9", "Unknown Code", "Sales", "General Shift", ["09:00", "18:00"], "", ""),  # not in master -> HR
]


def routing_workbook() -> bytes:
    wb = Workbook()
    wb.active.title = "Summary"
    ws = wb.create_sheet("Employee_Master")
    ws.append(["Employee_Code", "Employee_Name", "Department", "DOJ", "Employee_Status", "HOD_Name", "HOD_Email", "Sub_Split_ID",
               "Report_To_Type", "Report_To_Email", "Reporting_Manager_Name", "Routing_Status", "Issues"])
    for code, name, dept, hod, hod_mail, sub, mgr, issue in MASTER:
        ws.append([code, name, dept, "2020-01-01", None, hod or None, hod_mail or None, sub or None, "", "", mgr or None, "", issue])
    rm = wb.create_sheet("Recipient_Master")
    rm.append(["Recipient_ID", "Report_To_Email", "Report_To_Type", "Employees", "Names", "HODs", "Active_Status", "Effective_From", "Effective_To"])
    rm.append(["R1", "lead.a@example.com", "DIRECT_MANAGER", 2, "", "", None, None, None])
    rm.append(["R2", "DIRECTOR_EMAIL_TBC", "DIRECTOR", 1, "", "", None, None, None])
    cfg = wb.create_sheet("Email_Routing_Config")
    cfg.append(["Report_Type", "Recipient_Role", "Delivery_Type", "Sender_Email", "Reply_To", "Active_Status", "Notes"])
    cfg.append(["Direct Report Attendance", "Direct manager (Sub split ID email)", "TO", "attendance@example.com", None, "ACTIVE", ""])
    cfg.append(["Direct Report Attendance", "HOD", "CC", None, None, "DISABLED", "Subject to HR approval"])
    cov = wb.create_sheet("Employee_Coverage")
    cov.append(["Employee_Code", "Employee_Name", "Department", "HOD_Name", "Reporting_Manager_Name", "Detail_Recipient", "Detail_Rule",
                "HOD_Summary_Recipient"])
    for code, det, summ in (("T1", "lead.a@example.com", "arun@example.com"), ("T2", "lead.a@example.com", "arun@example.com"),
                            ("T3", "arun@example.com", "arun@example.com"), ("T4", "rahul@example.com", "rahul@example.com"),
                            ("D1", "DIRECTOR_EMAIL_TBC", "HR_EXCEPTION_QUEUE"), ("C1", "HR_EXCEPTION_QUEUE", "HR_EXCEPTION_QUEUE")):
        cov.append([code, "", "", "", "", det, "", summ])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def load(s, settings, **email):
    data = routing_workbook()
    emp.import_rows(s, emp.read_master_file("routing.xlsx", data), "tester")
    out = routing.apply_workbook(s, settings, emp.read_routing_extras("routing.xlsx", data), "tester")
    if email:
        save_email_settings(s, get_email_settings(s, settings).model_copy(update=email), "tester")
    return out


def test_routing_rules_and_workbook(engine, settings):
    with session_scope(engine) as s:
        applied = load(s, settings)
        assert applied["coverage"] == {"checked": 6, "differences": 0, "examples": []}
        assert applied["config"]["applied"] == {"team_emails": True, "sender": "attendance@example.com", "hod_cc_on_team": False}
        assert applied["recipients"]["imported"] == 1                       # placeholder address skipped
        r = {x.code: x for x in routing.routes(s)}
        assert (r["T1"].detail_to, r["T1"].summary_to) == ("lead.a@example.com", "arun@example.com")
        assert (r["T4"].detail_to, r["T4"].rule) == ("rahul@example.com", "No Sub split ID: HOD")
        assert r["D1"].detail_to == routing.DIRECTOR and r["D1"].summary_to is None
        assert (r["C1"].detail_to, r["C1"].issue) == (routing.HR, "HOD_EMAIL_CONFLICT")
        ov = routing.overview(s, get_email_settings(s, settings))
        recs = {x["key"]: x for x in ov["recipients"]}
        assert ov["employees"] == 6 and ov["detail_total"] == 6 and ov["unique"]
        assert (recs["arun@example.com"]["role"], recs["arun@example.com"]["team"], recs["arun@example.com"]["summary"]) == ("HOD + Team lead", 1, 3)
        assert recs["lead.a@example.com"]["role"] == "Team lead" and recs["lead.a@example.com"]["name"] == "Lead A"
        assert recs["rahul@example.com"]["name"] == "Rahul Sharma"
        assert [h["code"] for h in ov["held"]] == ["C1"]


def test_plan_content_and_privacy(engine, settings):
    with session_scope(engine) as s:
        load(s, settings, approval_required=True)
        up, items, note = service.upload_files_and_send(s, settings, [("s.xlsx", summary_file(ATTENDANCE))], "tester")
        assert "ready" in note and {i.status for i in items} == {mail.PENDING}
        by = {i.recipient_key: i for i in items}
        assert set(by) == {"lead.a@example.com", "arun@example.com", "rahul@example.com", "DIRECTOR", "HR"}
        assert by["lead.a@example.com"].subject == "Daily Attendance | 13-Nov-2026 | Lead A"
        hr = json.loads(by["HR"].content)["exceptions"]
        assert {x["code"]: x["issue"] for x in hr} == {"C1": "HOD_EMAIL_CONFLICT", "X9": mail.NOT_IN_MASTER}
        c = json.loads(by["lead.a@example.com"].counts)["team"]
        assert (c["total"], c["present"], c["absent"], c["attention"]) == (2, 1, 1, 1)
        rahul = json.loads(by["rahul@example.com"].counts)["team"]
        assert rahul["wfh"] == 1 and rahul["attendance_pct"] == 100.0
        html, text, files = mail.render(s, settings, by["lead.a@example.com"])
        assert "Team One B" in html and "Absent" in html and "Team One A" not in html     # only people needing attention
        assert "Arun Direct" not in html and "Conflict Person" not in html               # privacy: own team only
        roster = load_workbook(io.BytesIO(files[0].content))["Team roster"]
        assert [roster.cell(r, 1).value for r in range(4, roster.max_row + 1)] == ["T2", "T1"]   # attention first
        html, _, files = mail.render(s, settings, by["arun@example.com"])
        assert "Department summary" in html and "Your team (1)" in html
        assert load_workbook(io.BytesIO(files[0].content)).sheetnames == ["Team roster", "Department summary", "Department roster"]
        html, _, _ = mail.render(s, settings, by["DIRECTOR"])
        assert "Company (6 employees)" in html and "Director Office staff (1)" in html
        dash = files[1].content
        assert b"Team One A" in dash and b"Unknown Code" not in dash


def test_approve_duplicate_guard_and_resend(engine, settings):
    with session_scope(engine) as s:
        load(s, settings, approval_required=True)
        up, items, _ = service.upload_files_and_send(s, settings, [("s.xlsx", summary_file(ATTENDANCE))], "tester")
        lead = next(i for i in items if i.recipient_key == "lead.a@example.com")
        mail.approve(s, settings, DAY, "approver", ids=[lead.id])                       # approve one
        assert lead.status == mail.SAVED and lead.approved_by == "approver"
        assert sum(i.status == mail.PENDING for i in mail.items_for(s, DAY)) == 4
        done = mail.approve(s, settings, DAY, "approver")                               # then the rest
        assert len(done) == 4
        out = sorted((settings.storage.area("outbox") / "2026-11-13").glob("*.eml"))
        assert len(out) == 5
        msgs = [email.message_from_bytes(p.read_bytes()) for p in out]
        assert all("," not in m["To"] and not m["Cc"] for m in msgs)                     # one recipient per email
        # Re-upload the same day: everything already sent -> nothing new.
        up2, items2, _ = service.upload_files_and_send(s, settings, [("s.xlsx", summary_file(ATTENDANCE))], "tester", replace=True)
        assert {i.status for i in items2} == {mail.DUPLICATE}
        assert mail.approve(s, settings, DAY, "approver") == []
        assert len(list((settings.storage.area("outbox") / "2026-11-13").glob("*.eml"))) == 5
        # An administrator can force a resend of one recipient.
        again = next(i for i in items2 if i.recipient_key == "lead.a@example.com")
        mail.send_items(s, settings, [again], "admin", force=True)
        assert again.status == mail.SAVED
        assert len(list((settings.storage.area("outbox") / "2026-11-13").glob("*.eml"))) == 6


def test_switches_held_cc_and_recipient_off(engine, settings):
    with session_scope(engine) as s:
        load(s, settings, approval_required=True, director_emails=[], hod_cc_on_team=True, hod_summary=False)
        routing.set_recipient(s, "rahul@example.com", False, None, "tester")
        _, items, _ = service.upload_files_and_send(s, settings, [("s.xlsx", summary_file(ATTENDANCE))], "tester")
        by = {i.recipient_key: i for i in items}
        assert by["DIRECTOR"].status == mail.HELD and "Director email not set" in by["DIRECTOR"].note
        assert by["rahul@example.com"].status == mail.DISABLED
        assert by["lead.a@example.com"].cc_addrs == "arun@example.com"                  # HOD CC (HR-approved switch)
        assert json.loads(by["arun@example.com"].content)["summary"] == []              # HOD summary switched off
        assert mail.approve(s, settings, DAY, "x") and by["DIRECTOR"].status == mail.HELD


def test_providers_use_their_apis(monkeypatch, tmp_path):
    calls = []

    def fake(method, url, **kw):
        calls.append((method, url, kw))
        return httpx.Response(200, json={"access_token": "tok"}) if "token" in url else httpx.Response(202)

    monkeypatch.setattr(httpx, "request", fake)
    msg = mailer.build_message("attendance@example.com", ["a@example.com"], "S", "<p>x</p>", "x", [])
    for k, v in {"GRAPH_TENANT_ID": "t", "GRAPH_CLIENT_ID": "c", "GRAPH_CLIENT_SECRET": "s", "GMAIL_CLIENT_ID": "c",
                 "GMAIL_CLIENT_SECRET": "s", "GMAIL_REFRESH_TOKEN": "r"}.items():
        monkeypatch.setenv(k, v)
    assert mailer.send(EmailSettings(mode="live", provider="graph", sender="attendance@example.com"), msg, tmp_path).status == "SENT"
    assert calls[1][1] == "https://graph.microsoft.com/v1.0/users/attendance@example.com/sendMail"
    assert calls[1][2]["headers"]["Authorization"] == "Bearer tok"
    assert mailer.send(EmailSettings(mode="live", provider="gmail", sender="attendance@example.com"), msg, tmp_path).status == "SENT"
    assert calls[3][1].endswith("/gmail/v1/users/me/messages/send") and "raw" in calls[3][2]["json"]
    monkeypatch.delenv("GRAPH_CLIENT_SECRET")
    with pytest.raises(mailer.MailError, match="GRAPH_CLIENT_SECRET"):
        mailer.send(EmailSettings(mode="live", provider="graph", sender="attendance@example.com"), msg, tmp_path)


def test_dashboard_json_cannot_break_out_of_script():
    from daily.render import dashboard_html_for

    html = dashboard_html_for("X", DAY, "T", {}, [], [], {"by": "Team", "rows": []}, [{"name": "</script><img src=x>"}], "%d")
    assert b"</script><img" not in html and b"\\u003c/script" in html


@pytest.fixture
def api(settings, engine, tmp_path):
    with TestClient(create_app(settings, engine, frontend_dist=tmp_path / "x")) as c:
        yield c


def test_mail_api(api, engine, settings):
    r = api.post("/api/v1/employees/import", headers=H, files={"file": ("APIS_Email_Routing_Master.xlsx", routing_workbook())})
    assert r.status_code == 200 and r.json()["routing"]["coverage"]["differences"] == 0
    with session_scope(engine) as s:
        save_email_settings(s, get_email_settings(s, settings).model_copy(update={"approval_required": True}), "tester")
    ov = api.get("/api/v1/routing").json()
    assert ov["employees"] == 6 and len(ov["recipients"]) == 5
    up = api.post("/api/v1/days/upload", headers=H, files={"file": ("s.xlsx", summary_file(ATTENDANCE))}).json()
    assert "ready" in up["send_note"] and not up["auto_sent"]
    day = api.get("/api/v1/days/2026-11-13/mail").json()
    assert day["approval_required"] and day["status"] == {"PENDING": 5}
    first = day["items"][0]
    p = api.get(f"/api/v1/mail/{first['id']}/preview")
    assert p.status_code == 200 and "sandbox" in p.headers["content-security-policy"] and "Daily Attendance" in p.text
    x = api.get(f"/api/v1/mail/{first['id']}/attachment/excel")
    assert x.status_code == 200 and x.headers["content-disposition"].endswith('.xlsx"')
    d = api.get(f"/api/v1/mail/{first['id']}/attachment/dashboard")
    assert "sandbox allow-scripts" in d.headers["content-security-policy"]
    sent = api.post("/api/v1/days/2026-11-13/mail/approve", headers=H, json={}).json()
    assert sent["sent_now"] == 5 and sent["status"] == {"SAVED": 5}
    assert api.post("/api/v1/days/2026-11-13/mail/approve", headers=H, json={}).json()["sent_now"] == 0
    again = api.post(f"/api/v1/mail/{first['id']}/resend", headers=H).json()
    assert again["status"] == "SAVED" and again["attempts"] == 2
    replan = api.post("/api/v1/days/2026-11-13/mail/plan", headers=H).json()
    assert set(replan["status"]) == {"SAVED", "DUPLICATE"}
    assert api.put("/api/v1/routing/recipients", headers=H, json={"email": "bad", "active": False}).status_code == 422
    assert api.put("/api/v1/routing/recipients", headers=H, json={"email": "rahul@example.com", "active": False}).json()["active"] is False


def test_watch_folder(isolated_env, tmp_path, capsys):
    import main

    main.main(["init-db"])
    folder = tmp_path / "drop"
    folder.mkdir()
    (folder / "AttendanceSummary.xlsx").write_bytes(summary_file(ATTENDANCE))
    (folder / "notes.txt").write_text("ignored")
    assert main.main(["watch", str(folder), "--once"]) == 0          # just written: not touched yet
    assert (folder / "AttendanceSummary.xlsx").exists()
    old = time.time() - 60
    os.utime(folder / "AttendanceSummary.xlsx", (old, old))          # settled for a while -> processed
    assert main.main(["watch", str(folder), "--once"]) == 0
    assert (folder / "processed" / "AttendanceSummary.xlsx").exists() and (folder / "notes.txt").exists()
    assert "13-Nov-2026" in capsys.readouterr().out
    (folder / "AttendanceSummary.xlsx").write_bytes(summary_file(ATTENDANCE))   # same day again -> failed folder
    os.utime(folder / "AttendanceSummary.xlsx", (old, old))
    main.main(["watch", str(folder), "--once"])
    assert (folder / "failed" / "AttendanceSummary.xlsx").exists()
    assert "already uploaded" in (folder / "failed" / "AttendanceSummary.xlsx.txt").read_text(encoding="utf-8")
