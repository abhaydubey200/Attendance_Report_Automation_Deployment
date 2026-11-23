"""Pocket HRMS On Duty Report (OnDutyReportAdmin, an HTML table saved as .xls): the third daily dataset.
Synthetic data only."""

from __future__ import annotations

import html
import json
from datetime import date

import pytest

from core.config import EmailSettings, Rules
from daily import analysis, mail, onduty, service
from daily import employees as emp
from daily.analysis import FileError
from daily.settings_store import save_email_settings
from database.connection import session_scope
from ingestion.file_inspector import inspect_file
from ingestion.file_reader import read_raw
from tests.integration.test_daily import CASES, _classify, summary_file
from tests.integration.test_permissions import PERMS, permission_file

DAY = date(2026, 11, 13)
HEAD = ["Company Name", "Employee Code", "Employee Name", "On Duty Date", "In Date", "In Time", "Out Date", "Out Time", "Created Date",
        "Total On Duty Hours", "Day Type", "Type", "Employee Remarks", "Overall Status", "Manager Name 1", "Manager Status 1",
        "Manager Status Date 1", "Manager Remark 1"]


def onduty_file(rows: list[tuple]) -> bytes:
    """rows of (code, On Duty Date dd/mm/yyyy, in, out, day type, remarks, status) -> Pocket HRMS's HTML '.xls'."""
    def tr(cells):
        return "<tr>" + "".join(f"<td>{html.escape(c)}</td>" for c in cells) + "</tr>"
    body = [tr(["APIS INDIA LTD"]), tr(["Head Office : X"]), tr(["On Duty Report 13/11/2026 - 13/11/2026"]), tr(["Report Runtime: x"]),
            "<tr>" + "".join(f"<th>{h}</th>" for h in HEAD) + "</tr>"]
    for code, day, t_in, t_out, day_type, remarks, status in rows:
        body.append(tr(["APIS INDIA LTD", code, "Name", day, day, t_in, day, t_out, "12/11/2026 09:00 AM", "08:30", day_type, "",
                        remarks, status, "Manager", status, "", "-"]))
    page = ('<html xmlns:o="urn:schemas-microsoft-com:office:office" xmlns:x="urn:schemas-microsoft-com:office:excel">'
            "<head><meta charset='utf-8'><style>td{}</style><script>alert(1)</script></head><body><table>"
            + "".join(body) + "</table></body></html>")
    return page.encode("utf-8")


# CASES: E2 late 11:15, E3 out 16:00 (left early), E4 one punch, E5 no punch (absent), E7 on PL leave
ODS = [("E5", "13/11/2026", "09:30", "18:00", "Full Day", "Work from home 🏠", "Approved"),
       ("E2", "13/11/2026", "09:30", "18:00", "Full Day", "Client audit at Roorkee", "Approved"),
       ("E4", "13/11/2026", "09:30", "18:00", "Full Day", "WFH", "Pending"),
       ("E3", "13/11/2026", "16:00", "18:00", "Second Half", "Exhibition", "Approved"),
       ("E7", "13/11/2026", "09:30", "18:00", "Full Day", "office work", "Approved"),
       ("E1", "13/11/2026", "09:30", "18:00", "Full Day", "wfh", "Rejected"),
       ("ZZ9", "13/11/2026", "09:30", "18:00", "Full Day", "visit", "Approved"),
       ("E6", "12/11/2026", "09:30", "18:00", "Full Day", "visit", "Approved")]


def _od_day(rows=ODS):
    raw, _ = read_raw(onduty_file(rows), "html")
    return onduty.parse_rows(raw)


def test_html_xls_is_read_and_binary_xls_refused():
    data = onduty_file(ODS)
    assert inspect_file("OnDutyReportAdmin.xls", data, (".xlsx", ".csv", ".xls"), 10 << 20).file_type == "html"
    raw, _ = read_raw(data, "html")
    assert raw[4][:3] == ["Company Name", "Employee Code", "Employee Name"] and raw[5][1] == "E5"
    assert not any("alert" in c for row in raw for c in row)                        # script text is dropped
    ole = bytes.fromhex("D0CF11E0A1B11AE1") + b"\0" * 100
    assert "save it as .xlsx" in inspect_file("x.xls", ole, (".xls",), 10 << 20).errors[0]
    assert not inspect_file("x.xls", b"just text", (".xls",), 10 << 20).ok


def test_parse_onduty_report():
    d = _od_day()
    assert len(d.requests) == 8 and d.dates == {DAY, date(2026, 11, 12)}
    q = {r.code: r for r in d.requests}
    assert (q["E5"].kind, q["E5"].status, q["E5"].full_day) == (onduty.WFH, onduty.APPROVED, True)
    assert q["E2"].kind == onduty.ON_DUTY and q["E4"].status == onduty.PENDING and q["E1"].status == onduty.OTHER
    assert q["E3"].full_day is False and q["E3"].label == "On duty approved (4:00 PM - 6:00 PM)"
    assert q["E5"].label == "Work from home approved (full day)"
    assert not hasattr(q["E5"], "remarks")                                          # the free text is never kept
    assert onduty._status("Partially Approved") == onduty.PENDING and onduty._status("Cancelled") == onduty.OTHER


def test_approved_counts_pending_is_shown():
    d, results, _ = _classify()
    by = {r.code: r for r in results}
    assert by["E5"].status == "ABSENT" and "LATE" in by["E2"].flags and "LEFT_EARLY" in by["E3"].flags
    stats = analysis.apply_onduty(results, _od_day(), d, Rules())
    assert stats == {"rows": 8, "today": 7, "other_dates": 1, "approved": 4, "pending": 1, "on_duty": 1, "wfh": 1, "part_day": 1,
                     "kept_status": 1, "excused_late": 0, "excused_early": 1, "not_in_file": 1}
    assert by["E5"].status == "WFH" and by["E5"].on_duty == "Work from home approved (full day)"
    assert by["E2"].status == "ON_DUTY" and "LATE" not in by["E2"].flags and by["E2"].late_minutes == 0
    assert by["E3"].status == "PRESENT" and "LEFT_EARLY" not in by["E3"].flags                 # part day: like a permission
    assert by["E4"].status == "MISSING_PUNCH" and "ON_DUTY_PENDING" in by["E4"].flags           # pending changes nothing
    assert by["E7"].status == "LEAVE" and by["E1"].on_duty is None                              # leave kept; rejected ignored
    row = {"status": "ABSENT", "flags": ["ON_DUTY_PENDING"], "on_duty": "Work from home pending (full day)"}
    assert mail.attention(row) == "Absent (work from home request pending, full day)"


def test_upload_three_files_then_on_duty_alone_and_recalculate(engine, settings):
    with session_scope(engine) as s:
        save_email_settings(s, EmailSettings(approval_required=True, director_emails=["director@example.com"]), "tester")
        for code, name, *_ in CASES[:9]:
            emp.create(s, {"code": code, "name": name, "department": "Ops", "hod_name": "Hod One", "hod_email": "hod1@example.com"},
                       "tester")
        up = service.process_files(s, settings, [("s.xlsx", summary_file(CASES)), ("p.xlsx", permission_file(PERMS))], "tester",
                                   kinds=["HRMS", "PERMISSION"])
        assert up.onduty_path is None and json.loads(up.insights)["sources"]["onduty_file"] is False
        # the On Duty Report on its own, later: merged with the stored files of that day (it covers two dates)
        up2 = service.process_files(s, settings, [("OnDutyReportAdmin.xls", onduty_file(ODS))], "tester", kinds=["ONDUTY"])
        assert (up2.original_filename, up2.permission_filename, up2.onduty_filename) == ("s.xlsx", "p.xlsx", "OnDutyReportAdmin.xls")
        ins = json.loads(up2.insights)
        assert ins["sources"]["onduty"]["approved"] == 4 and ins["sources"]["permissions"]["approved"] == 1
        assert any("on-duty request(s) on 13-Nov-2026: 4 approved" in h["text"] for h in ins["scopes"]["ALL"]["highlights"])
        rows = {r["code"]: r for r in service.rows_for(s, up2.upload_id)}
        assert rows["E5"]["status"] == "WFH" and rows["E5"]["on_duty"] == "Work from home approved (full day)"
        assert rows["E2"]["permission"] == "Approved 9:30 AM - 11:30 AM" and rows["E2"]["status"] == "ON_DUTY"
        with pytest.raises(service.AlreadyUploaded, match="On Duty Report"):
            service.process_files(s, settings, [("o.xls", onduty_file(ODS))], "tester")
        with pytest.raises(FileError, match="put in the Pocket HRMS Permission Report box"):
            service.process_files(s, settings, [("o.xls", onduty_file(ODS))], "tester", replace=True, kinds=["PERMISSION"])
        again = service.recalculate(s, settings, DAY, "tester")
        assert again.onduty_filename == "OnDutyReportAdmin.xls" and json.loads(again.insights)["sources"]["onduty"]["wfh"] == 1
        # HR's action list has the pending request
        items = mail.build_plan(s, settings, again, "tester")
        hr = next(i for i in items if i.recipient_key == "HR")
        assert json.loads(hr.counts)["hr"]["onduty"] == 1 and "1 on-duty request(s) pending" in hr.subject
        body, text, files = mail.render(s, settings, hr)
        assert "On-duty / work from home requests waiting for approval" in body and "Work from home request pending, full day" in body
        assert any(a.filename.endswith(".xlsx") for a in files)
        hod = next(i for i in items if i.recipient_key == "hod1@example.com")
        body, _, _ = mail.render(s, settings, hod)
        assert "work from home request pending, full day" in body               # E4: missing punch + pending request
        for item in items:                                                       # every email and attachment can be produced
            mail.render(s, settings, item)


def test_all_three_together_and_wrong_dates(engine, settings):
    with session_scope(engine) as s:
        with pytest.raises(FileError, match="upload it together"):                # no attendance for any of its dates
            service.process_files(s, settings, [("o.xls", onduty_file(ODS))], "tester")
        up = service.process_files(s, settings, [("s.xlsx", summary_file(CASES)), ("p.xlsx", permission_file(PERMS)),
                                                 ("o.xls", onduty_file(ODS))], "tester")
        assert up.report_date == DAY and up.onduty_filename == "o.xls"
        other = onduty_file([("E1", "10/11/2026", "09:30", "18:00", "Full Day", "visit", "Approved")])
        with pytest.raises(FileError, match="different dates"):
            service.process_files(s, settings, [("s.xlsx", summary_file(CASES)), ("o.xls", other)], "tester", replace=True)


def test_api_upload_with_on_duty_box(settings, engine, tmp_path):
    """The Upload screen sends the On Duty Report in its own box; the day shows the file and the counts."""
    from fastapi.testclient import TestClient

    from api.main import create_app
    from tests.integration.test_api import H, with_auth_mode

    with TestClient(create_app(with_auth_mode(settings, "none"), engine, frontend_dist=tmp_path / "no-dist")) as c:
        files = {"hrms": ("s.xlsx", summary_file(CASES)), "permission": ("p.xlsx", permission_file(PERMS)),
                 "onduty": ("OnDutyReportAdmin.xls", onduty_file(ODS))}
        r = c.post("/api/v1/days/upload", files=files, data={"send_mode": "manual"}, headers=H)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["onduty_file"] == "OnDutyReportAdmin.xls" and body["insights"]["sources"]["onduty"]["approved"] == 4
        assert not body["auto_sent"]
        day = c.get(f"/api/v1/days/{DAY.isoformat()}").json()
        assert {x["code"]: x["on_duty"] for x in day["rows"]}["E5"] == "Work from home approved (full day)"
        assert c.get("/api/v1/days").json()[0]["has_onduty"] is True
        # the wrong file in the On Duty box is refused with a clear message
        r = c.post("/api/v1/days/upload", files={"onduty": ("p.xlsx", permission_file(PERMS))}, data={"replace": "true"}, headers=H)
        assert r.status_code == 422 and "On Duty Report box" in r.json()["detail"]
