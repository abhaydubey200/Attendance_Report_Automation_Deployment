"""Unattended jobs: 09:30 daily run, lock, history, alerts, backup, month-end reports and guarded cleanup.
Synthetic data only (example.com addresses)."""

from __future__ import annotations

import io
import json
import os
import sqlite3
import time
from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient
from openpyxl import load_workbook

from api.main import CSRF_HEADER, create_app
from core.config import EmailSettings
from daily import employees as emp
from daily import jobs, mail, monthly, service
from daily.settings_store import get_email_settings, save_email_settings
from database.connection import session_scope
from database.models.daily import JobRun
from demo.synthetic import build_master_xlsx, build_permission_xlsx, build_summary_xlsx

H = {CSRF_HEADER: "1"}
DAY = date(2026, 11, 13)


_FILES: dict = {}


def _file(builder, day):
    """Same bytes every time (a workbook generated a second later would carry a different timestamp)."""
    key = (builder.__name__, day)
    if key not in _FILES:
        _FILES[key] = builder(day)
    return _FILES[key]


def drop(settings, day=DAY, permission=True):
    inbox = settings.jobs.inbox_dir
    inbox.mkdir(parents=True, exist_ok=True)
    (inbox / f"AttendanceSummary_{day:%Y%m%d}.xlsx").write_bytes(_file(build_summary_xlsx, day))
    if permission:
        (inbox / f"PermissionReportAdmin_{day:%Y%m%d}.xlsx").write_bytes(_file(build_permission_xlsx, day))
    return inbox


@pytest.fixture
def master(engine):
    with session_scope(engine) as s:
        emp.import_rows(s, emp.read_master_file("m.xlsx", build_master_xlsx()), "tester")


def runs(engine):
    with session_scope(engine) as s:
        return jobs.history(s)


# ---------------------------------------------------------------------------- daily
def test_daily_job_sends_once_and_is_idempotent(engine, settings, master):
    inbox = drop(settings)
    r = jobs.run_daily(settings, engine, DAY)
    assert r["status"] == jobs.SUCCESS and len(r["processed"]) == 2 and r["send_mode"] == "auto"
    assert r["emails"].get(mail.SAVED, 0) > 5 and not (inbox / f"AttendanceSummary_{DAY:%Y%m%d}.xlsx").exists()
    assert (inbox / "processed" / DAY.isoformat()).is_dir()
    sent = len(list((settings.storage.area("outbox") / DAY.isoformat()).glob("*.eml")))
    # The scheduler retries / runs again: nothing new to process, nothing re-sent.
    drop(settings)                                                     # same files dropped again
    r2 = jobs.run_daily(settings, engine, DAY)
    assert r2["status"] == jobs.SUCCESS and r2["processed"] == []
    assert len(list((settings.storage.area("outbox") / DAY.isoformat()).glob("*.eml"))) == sent
    h = runs(engine)
    assert [x["status"] for x in h[:2]] == [jobs.SUCCESS, jobs.SUCCESS] and h[0]["job"] == "DAILY" and h[0]["seconds"] is not None


def test_daily_job_without_file_fails_and_alerts(engine, settings, master):
    settings.jobs.inbox_dir.mkdir(parents=True, exist_ok=True)
    r = jobs.run_daily(settings, engine, DAY)
    assert r["status"] == jobs.FAILED and "No Pocket HRMS Attendance Summary" in r["problem"]
    assert r["alert"] == "SAVED"                                        # test mode: alert saved to outbox/alerts
    assert list((settings.storage.area("outbox") / "alerts").glob("*.eml"))


def test_permission_required_blocks_until_it_arrives(engine, settings, master):
    s2 = settings.model_copy(update={"jobs": settings.jobs.model_copy(update={"permission_required": True})})
    drop(s2, permission=False)
    assert jobs.run_daily(s2, engine, DAY)["status"] == jobs.FAILED
    drop(s2)
    r = jobs.run_daily(s2, engine, DAY)
    assert r["status"] == jobs.SUCCESS and r["permission_report"]


def test_wait_for_permission_setting_blocks_the_daily_job(engine, settings, master):
    with session_scope(engine) as s:
        save_email_settings(s, get_email_settings(s, settings).model_copy(update={"wait_for_permission": True}), "tester")
    drop(settings, permission=False)
    r = jobs.run_daily(settings, engine, DAY)
    assert r["status"] == jobs.FAILED and "wait for the Permission Report" in r["problem"] and r["alert"]
    with session_scope(engine) as s:
        assert mail.items_for(s, DAY) == []                                             # nothing prepared, nothing sent
    drop(settings)
    r = jobs.run_daily(settings, engine, DAY)
    assert r["status"] == jobs.SUCCESS and r["permission_report"] and r["emails"].get(mail.SAVED, 0) > 5


def test_daily_job_delivers_outbox_saves_after_switching_to_live(engine, settings, master, monkeypatch):
    import httpx

    drop(settings)
    first = jobs.run_daily(settings, engine, DAY)
    saved = first["emails"][mail.SAVED]
    sent = []
    monkeypatch.setattr(httpx, "request", lambda m, url, **kw: sent.append(url) or (
        httpx.Response(200, json={"access_token": "t"}) if "token" in url else httpx.Response(200, json={"id": "m"})))
    for k in ("GMAIL_CLIENT_ID", "GMAIL_CLIENT_SECRET", "GMAIL_REFRESH_TOKEN"):
        monkeypatch.setenv(k, "x")
    with session_scope(engine) as s:
        save_email_settings(s, get_email_settings(s, settings).model_copy(update={"mode": "live",
                                                                                  "sender": "attendance@example.com"}), "tester")
    r = jobs.run_daily(settings, engine, DAY)
    assert r["status"] == jobs.SUCCESS and r["emails"].get(mail.SENT) == saved and mail.SAVED not in r["emails"]
    assert sum("messages/send" in u for u in sent) == saved
    assert jobs.run_daily(settings, engine, DAY)["emails"].get(mail.SENT) == saved and sum("messages/send" in u for u in sent) == saved


def test_failed_emails_are_retried_alone(engine, settings, master, monkeypatch):
    import httpx

    drop(settings)
    monkeypatch.setattr(mail, "SLEEP", lambda _s: None)
    monkeypatch.setattr(httpx, "request", lambda *a, **k: httpx.Response(503, text="Gmail unavailable"))
    for k in ("GMAIL_CLIENT_ID", "GMAIL_CLIENT_SECRET", "GMAIL_REFRESH_TOKEN"):
        monkeypatch.setenv(k, "x")
    with session_scope(engine) as s:
        save_email_settings(s, get_email_settings(s, settings).model_copy(update={"mode": "live",
                                                                                  "sender": "attendance@example.com"}), "tester")
    r = jobs.run_daily(settings, engine, DAY)
    assert r["status"] == jobs.PARTIAL and r["emails"].get(mail.FAILED)
    with session_scope(engine) as s:
        save_email_settings(s, get_email_settings(s, settings).model_copy(update={"mode": "test"}), "tester")
        failed_before = sum(1 for i in mail.items_for(s, DAY) if i.status == mail.FAILED)
    r2 = jobs.run_daily(settings, engine, DAY)
    assert r2["status"] == jobs.SUCCESS and r2["emails"].get(mail.SAVED) == failed_before


def test_nothing_is_sent_if_any_email_cannot_be_built(engine, settings, master, monkeypatch):
    drop(settings)
    real = mail.render

    def broken(session, s, item):
        if item.recipient_key == "DIRECTOR":
            raise RuntimeError("attachment generation failed")
        return real(session, s, item)

    monkeypatch.setattr(mail, "render", broken)
    with pytest.raises(RuntimeError):
        jobs.run_daily(settings, engine, DAY)
    assert not (settings.storage.area("outbox") / DAY.isoformat()).exists()
    assert runs(engine)[0]["status"] == jobs.FAILED


def test_lock_prevents_a_second_run(engine, settings, master):
    drop(settings)
    with jobs.job_lock(settings, "daily"):
        with pytest.raises(jobs.JobLocked):
            jobs.run_daily(settings, engine, DAY)
    lock = settings.storage.area("locks") / "daily.lock"
    lock.write_text("stale")
    old = time.time() - 3 * 3600
    os.utime(lock, (old, old))                                         # abandoned lock is ignored
    assert jobs.run_daily(settings, engine, DAY)["status"] == jobs.SUCCESS


def test_manual_mode_only_prepares(engine, settings, master):
    drop(settings)
    r = jobs.run_daily(settings, engine, DAY, mode="manual")
    assert r["status"] == jobs.SUCCESS and set(r["emails"]) <= {mail.PENDING, mail.HELD, mail.DISABLED}
    assert r["verified"] == r["emails"][mail.PENDING]


# ---------------------------------------------------------------------------- backup
def test_backup_is_consistent_and_pruned(engine, settings):
    folder = settings.storage.area("backups")
    folder.mkdir(parents=True)
    old = folder / "attendance_20200101_000000.db"
    old.write_bytes(b"x")
    os.utime(old, (time.time() - 90 * 86400,) * 2)
    r = jobs.backup(settings, engine)
    assert r["status"] == jobs.SUCCESS and r["integrity"] == "ok" and r["pruned"] == 1 and not old.exists()
    con = sqlite3.connect(r["file"])
    assert con.execute("select count(*) from employee").fetchone()[0] == 0
    con.close()
    with sqlite3.connect(settings.database.path) as live:
        assert live.execute("PRAGMA journal_mode").fetchone()[0] == "wal"


# ---------------------------------------------------------------------------- monthly + cleanup
def _month_of_uploads(engine, settings, days=3):
    with session_scope(engine) as s:
        for i in range(days):
            d = DAY - timedelta(days=i)
            service.process_files(s, settings, [("s.xlsx", build_summary_xlsx(d)), ("p.xlsx", build_permission_xlsx(d))], "tester")


def test_monthly_report_archive_and_guarded_cleanup(engine, settings, master):
    _month_of_uploads(engine, settings)
    r = monthly.generate(settings, engine, "2026-11", mode="manual")
    assert r["status"] == jobs.SUCCESS and r["days"] == 3 and r["employees"] == 42 and os.path.isfile(r["archive"])
    with session_scope(engine) as s:
        items = monthly.items(s, "2026-11")
        assert items and all(i.subject.startswith("Monthly Attendance | Nov-2026 | ") for i in items)
        assert not mail.items_for(s, date(2026, 11, 30))                # monthly mails stay off the daily screen
        director = next(i for i in items if i.recipient_key == "MONTHLY:DIRECTOR")
        html, text, files = mail.render(s, settings, director)
        assert "Monthly Company Attendance Report" in html and "Next-month planning" not in html and "Teams at a glance" in html and "not a measure of productivity" not in html and "Details:" not in html
        assert load_workbook(io.BytesIO(files[0].content)).sheetnames == ["Summary", "Teams", "Insights", "Needs attention", "Weeks", "Day by day",
                                                                         "Employees", "Calendar"]
        assert "Teams at a glance" in html          # (one week of test data: no week table)
        assert 'data-act="tab:teams"' in files[1].content.decode()
        # HR: the month-end payroll checklist (company-wide), never a list of "your team"
        hr = next(i for i in items if i.recipient_key == "MONTHLY:HR")
        h_html, h_text, h_files = mail.render(s, settings, hr)
        assert "Monthly HR Payroll Checklist" in h_html and "Dear HR team" in h_html and "Before payroll" in h_text
        assert "Payroll" not in load_workbook(io.BytesIO(h_files[0].content)).sheetnames
        # an HOD: grouped action list, no team table, no HOD names, payroll sheet without an HOD column
        hod = next(i for i in items if i.role.startswith("Monthly - HOD") or i.role.startswith("Monthly - Team"))
        o_html, _, o_files = mail.render(s, settings, hod)
        assert "Monthly Team Attendance Report" in o_html and "Teams at a glance" not in o_html and "HOD" not in o_html
        wb = load_workbook(io.BytesIO(o_files[0].content))
        assert wb.sheetnames == ["Summary", "Insights", "Needs attention", "Weeks", "Day by day", "Employees", "Calendar"]
        assert "Key takeaways" not in o_html and "HOD's team" not in [c.value for c in wb["Employees"][1]]
        assert 'data-act="tab:teams"' not in o_files[1].content.decode()
        dash = files[1].content.decode()
        assert files[1].filename.endswith("_dashboard.html") and "Monthly Company Attendance Report" in dash
        assert "Key takeaways" in dash and 'data-act="tab:actions"' in dash and "Dear Director" in dash
        assert "Department" not in dash and "</script><script>" not in dash.replace("</script>\n<script>", "")
        sent = mail.send_items(s, settings, [i for i in items if i.status == mail.PENDING], "tester")
        assert sent and {i.status for i in sent} == {mail.SAVED}
    # cleanup guard: inside the keep window -> blocked
    blocked = monthly.cleanup(settings, engine, "2026-11", confirm=True, today=date(2026, 12, 5))
    assert blocked["status"] == "BLOCKED" and any("kept" in p for p in blocked["problems"])
    later = date(2027, 1, 5)
    # no backup since the archive -> blocked
    assert any("backup" in p for p in monthly.cleanup(settings, engine, "2026-11", today=later)["problems"])
    jobs.backup(settings, engine)
    preview = monthly.cleanup(settings, engine, "2026-11", confirm=False, today=later)
    assert preview["status"] == "PREVIEW" and preview["has_rows"]
    done = monthly.cleanup(settings, engine, "2026-11", confirm=True, today=later)
    assert done["status"] == jobs.SUCCESS and done["rows_deleted"] == 126
    with session_scope(engine) as s:
        assert monthly.summaries(s)[0]["status"] == "CLEANED"           # the summary stays
    assert monthly.cleanup(settings, engine, "2026-11", confirm=True, today=later)["status"] == "BLOCKED"


def test_archive_tampering_blocks_cleanup(engine, settings, master):
    _month_of_uploads(engine, settings, days=1)
    r = monthly.generate(settings, engine, "2026-11", mode="manual")
    jobs.backup(settings, engine)
    with open(r["archive"], "ab") as f:
        f.write(b"changed")
    res = monthly.cleanup(settings, engine, "2026-11", confirm=True, today=date(2027, 1, 5))
    assert res["status"] == "BLOCKED" and any("changed" in p for p in res["problems"])


def test_cleanable_before():
    assert monthly.cleanable_before(date(2026, 12, 5), 2) == "2026-11"
    assert monthly.cleanable_before(date(2027, 1, 1), 2) == "2026-12"
    assert monthly.cleanable_before(date(2027, 1, 1), 3) == "2026-11"
    assert monthly.previous_month(date(2026, 12, 1)) == "2026-11"


# ---------------------------------------------------------------------------- over HTTP
@pytest.fixture
def api(settings, engine, tmp_path):
    with TestClient(create_app(settings, engine, frontend_dist=tmp_path / "x")) as c:
        yield c


def test_automation_api(api, settings, engine, master):
    drop(settings)
    r = api.post("/api/v1/jobs/daily", headers=H, json={"report_date": DAY.isoformat(), "send_mode": "manual"})
    assert r.status_code == 200 and r.json()["status"] == "SUCCESS"
    h = api.get("/api/v1/jobs").json()
    assert h["runs"][0]["job"] == "DAILY" and h["runs"][0]["trigger"] == "MANUAL" and h["inbox"].endswith("inbox")
    assert api.post("/api/v1/jobs/backup", headers=H).json()["status"] == "SUCCESS"
    m = api.post("/api/v1/monthly", headers=H, json={"month": "2026-11", "send_mode": "manual"}).json()
    assert m["status"] == "SUCCESS"
    assert api.get("/api/v1/monthly").json()[0]["month"] == "2026-11"
    d = api.get("/api/v1/monthly/2026-11").json()
    assert d["items"] and d["summary"]["company"]["employees"] == 42
    sent = api.post("/api/v1/monthly/2026-11/approve", headers=H, json={}).json()
    assert sent["sent_now"] == len([i for i in d["items"] if i["status"] == "PENDING"])
    assert api.get("/api/v1/monthly/2026-11/archive").status_code == 200
    assert api.post("/api/v1/monthly/2026-11/cleanup", headers=H, json={"confirm": True}).json()["status"] == "BLOCKED"
    assert api.post("/api/v1/monthly", headers=H, json={"month": "Nov"}).status_code == 422
