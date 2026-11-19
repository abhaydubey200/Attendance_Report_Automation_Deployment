"""Pocket HRMS Permission Report (short-leave permissions): the second daily dataset. Synthetic data only."""

from __future__ import annotations

import io
import json
from datetime import date

import pytest
from openpyxl import Workbook

from core.config import EmailSettings, Rules
from daily import analysis, mail, permissions, service
from daily.analysis import FileError
from daily.settings_store import save_email_settings
from database.connection import session_scope
from tests.integration.test_daily import CASES, _classify, summary_file

DAY = date(2026, 11, 13)


def permission_file(rows: list[tuple], title=True) -> bytes:
    """rows of (code, PerDate dd/mm/yyyy, from, to, status)"""
    wb = Workbook()
    ws = wb.active
    if title:
        for line in (["APIS INDIA LTD"], ["Head Office : X"], ["Permission Report Manager"], []):
            ws.append(line)
    ws.append(["EmployeeCode", "EmployeeName", "AppliedDate", "PerDate", "PerHour", "PerToHour", "ApprovedDate", "Reason", "Status"])
    for code, day, start, end, status in rows:
        ws.append([code, "Name ", f"{day} 08:00 AM", day, start, end, "", "private reason", status])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


# CASES: E2 in 11:15 (late), E3 out 16:00 (left early, short hours)
PERMS = [("E2", "13/11/2026", "09:30", "11:30", "Approved"), ("E3", "13/11/2026", "16:00", "18:00", "Pending"),
         ("E1", "12/11/2026", "16:00", "18:00", "Approved"), ("E9", "13/11/2026", "10:00", "12:00", "Rejected"),
         ("ZZ1", "13/11/2026", "10:00", "11:00", "Approved")]


def _perm_day(rows=PERMS):
    from ingestion.file_reader import read_raw

    raw, _ = read_raw(permission_file(rows), "xlsx")
    return permissions.parse_rows(raw)


def test_parse_permission_report():
    day = _perm_day()
    assert len(day.permissions) == 5 and day.dates == {date(2026, 11, 13), date(2026, 11, 12)}
    p = day.permissions[0]
    assert (p.code, p.start, p.end, p.status, p.window) == ("E2", "09:30", "11:30", permissions.APPROVED, "9:30 AM - 11:30 AM")
    assert day.permissions[3].status == permissions.OTHER
    assert not hasattr(p, "reason")                                       # the free-text reason is never kept


def test_approved_excuses_pending_is_shown():
    d, results, _ = _classify()
    by = {r.code: r for r in results}
    assert "LATE" in by["E2"].flags and "LEFT_EARLY" in by["E3"].flags
    stats = analysis.apply_permissions(results, _perm_day(), d, Rules())
    assert stats == {"rows": 5, "today": 4, "approved": 1, "pending": 1, "other_dates": 1, "excused_late": 1,
                     "excused_early": 0, "not_in_file": 1}
    assert "LATE" not in by["E2"].flags and by["E2"].late_minutes == 0 and "PERMISSION" in by["E2"].flags
    assert by["E2"].permission == "Approved 9:30 AM - 11:30 AM"
    assert "LEFT_EARLY" in by["E3"].flags and "PERMISSION_PENDING" in by["E3"].flags      # pending excuses nothing
    assert by["E3"].permission == "Pending 4:00 PM - 6:00 PM" and by["E9"].permission is None   # rejected ignored
    row = {"status": by["E3"].status, "flags": by["E3"].flags, "late_minutes": 0, "early_minutes": by["E3"].early_minutes,
           "permission": by["E3"].permission}
    assert mail.attention(row).endswith("(permission pending 4:00 PM - 6:00 PM)")


def test_upload_with_permission_report_and_waiting(engine, settings):
    with session_scope(engine) as s:
        save_email_settings(s, EmailSettings(approval_required=True, director_emails=["director@example.com"]), "tester")
        up, items, note = service.upload_files_and_send(s, settings, [("s.xlsx", summary_file(CASES))], "tester")
        assert items == [] and "Waiting for the Permission Report" in note
        ins = json.loads(up.insights)
        assert any("Permission Report not uploaded" in h["text"] for h in ins["scopes"]["ALL"]["highlights"])
        up2, items, note = service.upload_files_and_send(s, settings, [("PermissionReportAdmin.xlsx", permission_file(PERMS))], "tester")
        assert up2.original_filename == "s.xlsx" and up2.permission_filename == "PermissionReportAdmin.xlsx" and items
        ins = json.loads(up2.insights)
        assert ins["sources"]["permissions"]["approved"] == 1
        assert any("short-leave permission" in h["text"] for h in ins["scopes"]["ALL"]["highlights"])
        rows = {r["code"]: r for r in service.rows_for(s, up2.upload_id)}
        assert rows["E2"]["permission"] == "Approved 9:30 AM - 11:30 AM" and "LATE" not in rows["E2"]["flags"]
        with pytest.raises(service.AlreadyUploaded, match="Permission Report"):
            service.process_files(s, settings, [("p.xlsx", permission_file(PERMS))], "tester")
        assert service.recalculate(s, settings, DAY, "tester").permission_filename == "PermissionReportAdmin.xlsx"


def test_multi_day_permission_report_needs_the_attendance_file(engine, settings):
    with session_scope(engine) as s:
        with pytest.raises(FileError, match="upload it together"):   # no attendance uploaded for any of its dates
            service.process_files(s, settings, [("p.xlsx", permission_file(PERMS))], "tester")
        up = service.process_files(s, settings, [("s.xlsx", summary_file(CASES)), ("p.xlsx", permission_file(PERMS))], "tester")
        assert up.report_date == DAY and up.permission_filename == "p.xlsx"
        other = permission_file([("E1", "10/11/2026", "16:00", "18:00", "Approved")])
        with pytest.raises(FileError, match="different dates"):
            service.process_files(s, settings, [("s.xlsx", summary_file(CASES)), ("p.xlsx", other)], "tester", replace=True)


def test_bizom_file_is_refused(engine, settings):
    bizom = ("Zone,SubzoneName,Name,User_Name,User_Id,Employee_Id,Role_id,DOJ,HQ,Designation,User_Status,Inactive_Date,Imei,"
             "Date_13-11-2026_Attendance_Status\nZ,S,A,SL1,1,SL1,7,,,SO,Active,,,P\n").encode()
    with session_scope(engine) as s, pytest.raises(FileError, match="Bizom is no longer used"):
        service.process_files(s, settings, [("bizom.csv", bizom)], "tester")


def test_pocket_hrms_minutes_are_not_padded():
    """Pocket HRMS writes the minutes without padding: 16:00 as "16:0" and 10:08 as "10:8" (real October 2026 report:
    a 2-hour short leave "10:8" to "12:8"). "10:80" is not a time, so a single digit is never read as tens."""
    from daily.permissions import _time

    assert [_time(v) for v in ("16:0", "10:8", "12:8", "10:4", "9:30", "09:30", "4:05 PM")] ==            ["16:00", "10:08", "12:08", "10:04", "09:30", "09:30", "16:05"]


def test_approved_afternoon_short_leave_excuses_leaving_early():
    """APIS's usual short leave is 4:00-6:00 PM: leaving at/after its start (15 min grace) is excused; earlier is not."""
    day, results, _ = _classify()
    e3 = next(r for r in results if r.code == "E3")                       # out 16:00, left early
    assert "LEFT_EARLY" in e3.flags
    perm_day = permissions.PermissionDay([permissions.Permission("E3", day, "16:00", "18:00", permissions.APPROVED)])
    stats = analysis.apply_permissions(results, perm_day, day, Rules())
    assert stats["excused_early"] == 1 and "LEFT_EARLY" not in e3.flags and e3.early_minutes == 0
    day, results, _ = _classify()
    e3 = next(r for r in results if r.code == "E3")
    perm_day = permissions.PermissionDay([permissions.Permission("E3", day, "16:30", "18:30", permissions.APPROVED)])
    assert analysis.apply_permissions(results, perm_day, day, Rules())["excused_early"] == 0   # left 30 min before it
    assert "LEFT_EARLY" in e3.flags
