"""Per-recipient routing and the daily emails (build brief: APIS Daily Attendance Auto-Mailer).
Synthetic people, example.com addresses only."""

from __future__ import annotations

import email
import email.policy
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
    ("T3", "Arun Direct", "Sales", "General Shift", ["11:20", "19:30"], "", ""),   # late (after 11:00) -> attention
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
        assert applied["config"]["applied"] == {"team_emails": True, "sender": "attendance@example.com"}   # DISABLED rows never switch emails off
        assert any("left on" in d for d in applied["config"]["disabled"])
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
        assert by["lead.a@example.com"].subject == "Daily Attendance | 13-Nov-2026 | Lead A | 1 absent"
        assert by["HR"].subject.endswith("| 2 record(s) to fix")
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
        assert "Your wider team" in html and "Your team" in html and "department" not in html.lower() and "today" not in html.lower()
        assert "1 of 1 people in your team needs attention on 13-Nov-2026: 1 late." in html                  # headline
        assert "2 of 3 people in your wider team need attention on 13-Nov-2026: 1 absent, 1 late." in html
        assert load_workbook(io.BytesIO(files[0].content)).sheetnames == ["Team roster", "Wider team roster"]   # no per-team summary in emails
        html, _, _ = mail.render(s, settings, by["DIRECTOR"])
        assert "Company &ndash; 13-Nov-2026" in html and "Director Office staff" in html
        assert "All 1 people in the Director Office are accounted for on 13-Nov-2026" in html
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


def test_live_mail_goes_through_the_gmail_api(monkeypatch, tmp_path):
    calls = []

    def fake(method, url, **kw):
        calls.append((method, url, kw))
        return httpx.Response(200, json={"access_token": "tok"}) if "token" in url else httpx.Response(200, json={"id": "m1"})

    monkeypatch.setattr(httpx, "request", fake)
    msg = mailer.build_message("attendance@example.com", ["a@example.com"], "S", "<p>x</p>", "x", [])
    for k, v in {"GMAIL_CLIENT_ID": "c", "GMAIL_CLIENT_SECRET": "s", "GMAIL_REFRESH_TOKEN": "r"}.items():
        monkeypatch.setenv(k, v)
    assert mailer.send(EmailSettings(mode="live", sender="attendance@example.com"), msg, tmp_path).status == "SENT"
    assert calls[0][1] == "https://oauth2.googleapis.com/token" and calls[0][2]["data"]["grant_type"] == "refresh_token"
    assert calls[1][1] == "https://gmail.googleapis.com/gmail/v1/users/me/messages/send"
    assert calls[1][2]["headers"]["Authorization"] == "Bearer tok" and "raw" in calls[1][2]["json"]
    monkeypatch.delenv("GMAIL_REFRESH_TOKEN")
    with pytest.raises(mailer.MailError, match="GMAIL_REFRESH_TOKEN"):
        mailer.send(EmailSettings(mode="live", sender="attendance@example.com"), msg, tmp_path)
    assert mailer.send(EmailSettings(mode="test"), msg, tmp_path).status == "SAVED"      # test mode never calls Gmail
    assert len(calls) == 2


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


def test_three_dataset_upload_with_manual_or_auto_sending(api, engine, settings):
    from demo.synthetic import build_permission_xlsx

    with session_scope(engine) as s:
        save_email_settings(s, get_email_settings(s, settings).model_copy(update={"approval_required": True}), "tester")
    opts = api.get("/api/v1/upload/options").json()
    assert opts["default_mode"] == "manual" and opts["can_import_master"] and opts["employees"] == 0
    # master only: imported, nothing else happens
    r = api.post("/api/v1/days/upload", headers=H, files={"master": ("APIS_Email_Routing_Master.xlsx", routing_workbook())}).json()
    assert r["master_import"]["added"] == 6 and r["report_date"] is None and "Employee master updated" in r["send_note"]
    # a file in the wrong box is refused
    bad = api.post("/api/v1/days/upload", headers=H, files={"permission": ("s.xlsx", summary_file(ATTENDANCE))})
    assert bad.status_code == 422 and "put in the Pocket HRMS Permission Report box" in bad.json()["detail"]
    # all three at once, manual: emails wait for approval
    r = api.post("/api/v1/days/upload", headers=H, data={"send_mode": "manual"}, files={
        "master": ("routing.xlsx", routing_workbook()), "hrms": ("s.xlsx", summary_file(ATTENDANCE)),
        "permission": ("p.xlsx", build_permission_xlsx(DAY))}).json()
    assert r["master_import"]["unchanged"] == 6 and r["file"] == "s.xlsx" and r["permission_file"] == "p.xlsx"
    assert r["send_mode"] == "manual" and not r["auto_sent"] and {m["status"] for m in r["mail"]} == {"PENDING"}
    # same day again with auto: replaces the files and sends at once (nobody was sent yet)
    r = api.post("/api/v1/days/upload", headers=H, data={"send_mode": "auto", "replace": "true"}, files={
        "hrms": ("s.xlsx", summary_file(ATTENDANCE)), "permission": ("p.xlsx", build_permission_xlsx(DAY))}).json()
    assert r["send_mode"] == "auto" and r["auto_sent"] and {m["status"] for m in r["mail"]} == {"SAVED"}
    assert api.post("/api/v1/days/upload", headers=H, data={"send_mode": "later"},
                    files={"hrms": ("s.xlsx", summary_file(ATTENDANCE))}).status_code == 422


def test_testing_address_receives_every_email_and_real_send_still_happens_later(engine, settings):
    with session_scope(engine) as s:
        load(s, settings, approval_required=True, director_emails=[], test_recipient="tester@example.com",
             test_cc=["boss@example.com"])
        _, items, _ = service.upload_files_and_send(s, settings, [("s.xlsx", summary_file(ATTENDANCE))], "tester")
        by = {i.recipient_key: i for i in items}
        assert by["DIRECTOR"].status == mail.PENDING and "Testing" in by["DIRECTOR"].note    # no address yet, still testable
        done = mail.approve(s, settings, DAY, "tester")
        assert {i.status for i in done} == {mail.TEST_SENT} and len(done) == 5
        msgs = [email.message_from_bytes(p.read_bytes(), policy=email.policy.default)
                for p in (settings.storage.area("outbox") / "2026-11-13").glob("*.eml")]
        assert len(msgs) == 5 and {m["To"] for m in msgs} == {"tester@example.com"} and {m["Cc"] for m in msgs} == {"boss@example.com"}
        lead = next(m for m in msgs if "Lead A" in m["Subject"])
        assert lead["Subject"].startswith("[TEST] Daily Attendance")
        body = lead.get_body(("html",)).get_content()
        assert "TEST EMAIL - in live use this goes to To: lead.a@example.com" in body
        # Testing again is allowed; switching the test address off sends to the real people (not "already sent").
        assert len(mail.approve(s, settings, DAY, "tester")) == 5
        save_email_settings(s, get_email_settings(s, settings).model_copy(update={"test_recipient": None,
                                                                                  "director_emails": ["director@example.com"]}), "tester")
        _, items2, _ = service.upload_files_and_send(s, settings, [("s.xlsx", summary_file(ATTENDANCE))], "tester", replace=True)
        assert {i.status for i in items2} == {mail.PENDING}
        assert len(mail.items_for(s, DAY)) == 5                      # the earlier test sends are replaced, not listed twice
        real = mail.approve(s, settings, DAY, "tester")
        assert {i.status for i in real} == {mail.SAVED}
        assert next(i for i in real if i.recipient_key == "lead.a@example.com").to_addrs == "lead.a@example.com"


def test_outbox_saves_in_test_mode_do_not_block_live_sending(engine, settings, monkeypatch):
    """Email = test saves to the outbox (SAVED); after switching to live the same day's emails are really sent."""
    calls = []

    def fake(method, url, **kw):
        calls.append(url)
        return httpx.Response(200, json={"access_token": "tok"}) if "token" in url else httpx.Response(200, json={"id": "m"})

    monkeypatch.setattr(httpx, "request", fake)
    for k in ("GMAIL_CLIENT_ID", "GMAIL_CLIENT_SECRET", "GMAIL_REFRESH_TOKEN"):
        monkeypatch.setenv(k, "x")
    with session_scope(engine) as s:
        load(s, settings, approval_required=True)
        service.upload_files_and_send(s, settings, [("s.xlsx", summary_file(ATTENDANCE))], "tester")
        assert {i.status for i in mail.approve(s, settings, DAY, "tester")} == {mail.SAVED}
        assert not calls
        save_email_settings(s, get_email_settings(s, settings).model_copy(update={"mode": "live",
                                                                                  "sender": "attendance@example.com"}), "tester")
        # still listed as approvable, and approving now delivers them through Gmail
        assert all(d["sendable"] for d in (mail.item_dict(i, mail.sendable_statuses(get_email_settings(s, settings)))
                                           for i in mail.items_for(s, DAY)))
        live = mail.approve(s, settings, DAY, "tester")
        assert len(live) == 5 and {i.status for i in live} == {mail.SENT}
        assert sum("messages/send" in u for u in calls) == 5
        assert mail.approve(s, settings, DAY, "tester") == []                          # sent once, never twice
        _, again, _ = service.upload_files_and_send(s, settings, [("s.xlsx", summary_file(ATTENDANCE))], "tester", replace=True)
        assert {i.status for i in again} == {mail.DUPLICATE}


def test_replan_in_live_mode_replaces_outbox_saves(engine, settings):
    with session_scope(engine) as s:
        load(s, settings, approval_required=True)
        service.upload_files_and_send(s, settings, [("s.xlsx", summary_file(ATTENDANCE))], "tester")
        mail.approve(s, settings, DAY, "tester")
        save_email_settings(s, get_email_settings(s, settings).model_copy(update={"mode": "live",
                                                                                  "sender": "attendance@example.com"}), "tester")
        _, items, _ = service.upload_files_and_send(s, settings, [("s.xlsx", summary_file(ATTENDANCE))], "tester", replace=True)
        assert {i.status for i in items} == {mail.PENDING}                             # not "already sent"
        assert len(mail.items_for(s, DAY)) == 5                                         # the outbox saves are superseded


def _r(status, *flags):
    return {"status": status, "flags": list(flags), "late_minutes": 30 if "LATE" in flags else 0, "early_minutes": 0}


def test_headline_subject_change_and_patterns():
    c = mail.counts([_r("ABSENT"), _r("PRESENT", "LATE"), _r("PRESENT"),
                     _r(mail.NO_RECORD), _r("NOT_TRACKED")])
    assert (c["attention"], c["no_record"], c["not_tracked"]) == (2, 1, 1)                 # "no record" is a count, not attention
    assert mail.headline(c, "your team", "13-Nov-2026") == "2 of 5 people in your team need attention on 13-Nov-2026: 1 absent, 1 late."
    assert "today" not in (mail.headline(c, "your team", "13-Nov-2026") or "")
    assert mail.headline(mail.counts([_r("PRESENT")]), "your team").startswith("All 1 people")
    assert mail.subject_numbers({"team": c, "summary": None, "company": None, "exceptions": 0}) == "1 absent · 1 late"
    assert mail.subject_numbers({"team": mail.counts([_r("PRESENT")]), "exceptions": 0}) == "all present"
    before = mail.counts([_r("ABSENT"), _r("ABSENT"), _r("PRESENT")])
    ch = mail.change(c, before)
    assert ch["absent"] == -1 and ch["late"] == 1 and ch["attendance_pct"] == 33.4
    assert mail.change(c, None) == {"absent": None, "late": None, "missing_punch": None, "attendance_pct": None}
    day = lambda status, *flags: {"date": None, "status": status, "flags": list(flags)}  # noqa: E731
    assert mail.pattern([day("ABSENT"), day("ABSENT"), day("ABSENT"), day("PRESENT")]) == "absent on the last 3 report days"
    assert mail.pattern([day("PRESENT", "LATE"), day("PRESENT", "LATE"), day("PRESENT"), day("PRESENT", "LATE")]) == "late on 3 of the last 4 report days"
    assert mail.pattern([day("MISSING_PUNCH"), day("PRESENT"), day("MISSING_PUNCH")]) == "missing punch on 2 of the last 3 report days"
    assert mail.pattern([day("ABSENT")]) is None                                               # one day is not a pattern


def test_email_shows_change_and_pattern_across_days(engine, settings):
    from datetime import timedelta

    with session_scope(engine) as s:
        load(s, settings, approval_required=True)
        for i in (2, 1):                                     # T2 absent on the two days before as well
            d = DAY - timedelta(days=i)
            service.process_upload(s, settings, "s.xlsx", summary_file(ATTENDANCE, day=d.strftime("%d/%m/%Y")), "tester")
        _, items, _ = service.upload_files_and_send(s, settings, [("s.xlsx", summary_file(ATTENDANCE))], "tester")
        lead = next(i for i in items if i.recipient_key == "lead.a@example.com")
        html, text, _ = mail.render(s, settings, lead)
    assert "absent on the last 3 report days" in html and "(absent on the last 3 report days)" in text
    assert "compared with 12-Nov-2026" in html and "same as before" in html


def test_emails_do_not_show_hod_team_or_manager_per_person():
    from daily import mail as m
    from daily.render import dashboard_html_for
    assert not {"hod", "team", "manager"} & {k for _, k, _ in m.ROSTER_COLS}
    row = {"code": "E1", "name": "A", "department": "D", "hod": "Secret HOD", "team": "Secret team", "manager": "Secret manager",
           "status": "PRESENT", "status_label": "Present", "flags": []}
    html = dashboard_html_for("APIS", date(2026, 11, 14), "t", {}, [], [], {"by": "Team", "rows": []}, [row], "%d-%b-%Y",
                              routing_columns=False).decode()
    assert "Secret" not in html
    assert "Secret HOD" in dashboard_html_for("APIS", date(2026, 11, 14), "t", {}, [], [], {"by": "Team", "rows": []}, [row],
                                              "%d-%b-%Y").decode()          # the in-app dashboard keeps them


def test_dashboard_view_buckets_actions_and_comparison():
    from daily.render import bucket, dashboard_view

    def row(code, status, *flags, **kw):
        return {"code": code, "name": code, "status": status, "flags": list(flags), "late_minutes": kw.get("late", 0),
                "early_minutes": kw.get("early", 0), "in_time": kw.get("i"), "out_time": kw.get("o"), "work_hours": kw.get("h"),
                "permission": kw.get("perm", "")}

    rows = [row("A", "ABSENT"), row("L", "PRESENT", "LATE", late=35, i="11:35", o="20:00", h=8.4),
            row("M", "MISSING_PUNCH", i="09:10"), row("P", "PRESENT", i="09:30", o="18:30", h=9.0),
            row("S", "PRESENT", "PERMISSION", "PERMISSION_PENDING", i="09:30", o="16:00", h=6.5, perm="Pending 4:00 PM - 6:00 PM"),
            row("W", "WFH"), row("O", "WEEK_OFF")]
    v = dashboard_view(rows, {}, previous_rows=[dict(r, status="PRESENT", flags=[]) for r in rows],
                       patterns={"A": "absent on the last 3 report days"})
    assert [bucket(r) for r in rows] == ["absent", "late", "missing", "present", "short_leave", "wfh", "not_counted"]
    assert sum(c["value"] for c in v["cards"]) == v["total"] == 7                     # every person counted once
    by = {x["code"]: x for x in v["exceptions"]}
    assert [x["code"] for x in v["exceptions"]] == ["A", "M", "L", "S"]                # absent first
    assert by["A"]["action"].startswith("Speak to the employee") and "Absent on the last 3" in by["A"]["details"]
    assert by["M"]["status"] == "Missing punch (out)" and by["L"]["in"] == "11:35 AM" and by["L"]["hours"] == "8:24"
    assert "approve" in by["S"]["action"] and "Permission pending" in by["S"]["details"]
    m = {x["label"]: x for x in v["metrics"]}
    assert m["Absent"]["trend"] == "bad" and m["Absent"]["delta"] == "▲ 1"
    assert m["Work from home"]["trend"] == "move"                                      # neither good nor bad
    assert m["Attendance"]["trend"] == "bad" and m["Attendance"]["delta"].endswith("pts")


def test_emailed_dashboard_greets_and_lists_actions(engine, settings):
    with session_scope(engine) as s:
        load(s, settings, approval_required=True)
        _, items, _ = service.upload_files_and_send(s, settings, [("s.xlsx", summary_file(ATTENDANCE))], "tester")
        lead = next(i for i in items if i.recipient_key == "lead.a@example.com")
        _, _, att = mail.render(s, settings, lead)
        html = next(a for a in att if a.filename.endswith(".html")).content.decode()
    assert "Dear Lead A," in html and "Daily Team Attendance Dashboard" in html
    assert "1 employee needs your attention" in html and "Follow up; apply leave or regularise in Pocket HRMS" in html
    import re
    text = re.sub(r'src="data:[^"]+"', "", html)                                     # the embedded logo is not text
    assert not re.search(r"\btoday\b", text, re.I) and "Department" not in text and "ARUN MISHRA" not in text


def test_email_body_has_no_hod_or_team_breakdown():
    from pathlib import Path
    tpl = (Path(__file__).parents[2] / "daily" / "templates" / "mail.html").read_text(encoding="utf-8")
    assert "company_by_hod" not in tpl and "summary_by_team" not in tpl


def test_logo_is_embedded_and_centred():
    from email import message_from_bytes
    from daily import branding
    from daily.mailer import build_message
    html = '<td align="center"><img src="cid:apis-logo"></td>'
    msg = build_message("a@x.com", ["b@x.com"], "s", html, "t", [])
    parts = {p.get_content_type(): p for p in message_from_bytes(msg.as_bytes()).walk()}
    assert "multipart/related" in parts and parts["image/png"]["Content-ID"] == "<apis-logo>"
    assert parts["image/png"].get_payload(decode=True) == branding.logo_png()
    assert "image/png" not in {p.get_content_type() for p in build_message("a@x.com", ["b@x.com"], "s", "<p>x</p>", "t", []).walk()}
    assert branding.inline_logo_for_browser(html).count("data:image/png;base64,") == 1


def test_no_hod_name_goes_to_director_even_with_an_email():
    from daily import routing
    from database.models.daily import Employee
    e = Employee(code="HO0034", name="Amit Anand", department="Director Office", hod_name=None, hod_email="amit@example.com")
    assert routing.route_employee(e).detail_to == routing.DIRECTOR


def test_email_headline_counts_people_once_and_names_the_missing_punch():
    rows = [{"status": "PRESENT", "flags": ["LATE", "LEFT_EARLY"], "late_minutes": 30, "early_minutes": 40},
            {"status": "PRESENT", "flags": ["LATE", "LEFT_EARLY"], "late_minutes": 10, "early_minutes": 5},
            {"status": "PRESENT", "flags": ["LEFT_EARLY"], "late_minutes": 0, "early_minutes": 20},
            {"status": "ABSENT", "flags": [], "late_minutes": 0, "early_minutes": 0},
            {"status": "MISSING_PUNCH", "flags": [], "late_minutes": 0, "early_minutes": 0, "in_time": None, "out_time": "18:11"},
            {"status": "PRESENT", "flags": [], "late_minutes": 0, "early_minutes": 0}]
    c = mail.counts(rows)
    assert mail.headline(c, "your team", "16-Nov-2026") == ("5 of 6 people in your team need attention on 16-Nov-2026: 1 absent, "
                                                           "1 missing punch, 2 late (both also left early), 1 left early.")
    assert mail.attention(rows[4]) == "Missing punch - no in-punch"
    director = {"team": mail.counts(rows[5:]), "summary": None, "company": c, "exceptions": 0}
    assert mail.subject_numbers(director) == "1 absent · 2 late · 1 missing punch"      # company figures, not Director Office


def test_always_cc_goes_on_every_email(engine, settings):
    with session_scope(engine) as s:
        load(s, settings, approval_required=True, always_cc=["HR.Head@example.com"], hr_emails=["hr.head@example.com"])
        _, items, _ = service.upload_files_and_send(s, settings, [("s.xlsx", summary_file(ATTENDANCE))], "tester")
        by = {i.recipient_key: i for i in items}
        assert all(i.cc_addrs == "hr.head@example.com" for k, i in by.items() if k != "HR")
        assert by["HR"].cc_addrs is None                          # already in To: not copied twice
        mail.approve(s, settings, DAY, "tester")
        msgs = [email.message_from_bytes(p.read_bytes(), policy=email.policy.default)
                for p in (settings.storage.area("outbox") / "2026-11-13").glob("*.eml")]
    assert sum(1 for m in msgs if m["Cc"] == "hr.head@example.com") == len(msgs) - 1


def test_email_has_action_column(engine, settings):
    with session_scope(engine) as s:
        load(s, settings, approval_required=True)
        _, items, _ = service.upload_files_and_send(s, settings, [("s.xlsx", summary_file(ATTENDANCE))], "tester")
        lead = next(i for i in items if i.recipient_key == "lead.a@example.com")
        html, text, _ = mail.render(s, settings, lead)
    assert ">Action</th>" in html and "Follow up; apply leave or regularise in Pocket HRMS" in html
    assert "-> Follow up" in text and "Download it and open it in Chrome or Edge" in html
