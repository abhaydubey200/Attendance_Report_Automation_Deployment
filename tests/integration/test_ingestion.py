"""Phases 2-4: inspection, validation, upload lifecycle, standardization, mapping."""

from __future__ import annotations

import io
import os
import zipfile
from datetime import date

import pytest
from openpyxl import Workbook
from sqlalchemy import func, select

from database.connection import session_scope
from database.models.attendance import LeaveRecordRow, SourceAttendance
from database.models.hr import DimDepartment, DimEmployee, EmployeeOrgHistory, EmployeeSourceMapping
from database.models.staging import UploadRegistry, UploadRow, ValidationIssue
from data_engine.employee_mapper import resolve_mapping
from ingestion.dataset_registry import load_dataset_registry
from ingestion.file_inspector import inspect_file, safe_filename
from ingestion.file_reader import read_table
from ingestion.schema_definition import SchemaDefinition
from ingestion.schema_service import SchemaError, get_active_schema, save_schema
from ingestion.upload_manager import UploadError, confirm_upload, exceptions_csv, inspect_upload
from ingestion.validator import ValidationStatus, validate_table
from tests.fixtures.synthetic import DAILY_ORDER, MASTER_ORDER, SCHEMAS, SOURCE_OF, build_dataset_files

DAY = date(2026, 11, 13)
EXT = (".csv", ".xlsx")
MB = 1024 * 1024


@pytest.fixture
def registry():
    """Bizom is switched off in production config (Pocket HRMS only since 14-Nov-2026), but its
    path is kept dormant and still tested: re-enable it for these synthetic tests only."""
    reg = load_dataset_registry()
    return reg.model_copy(update={"datasets": tuple(
        d.model_copy(update={"active": True}) if d.dataset_id == "BIZOM_ATTENDANCE" else d for d in reg.datasets)})


def define_all(engine):
    with session_scope(engine) as s:
        for ds, schema in SCHEMAS.items():
            save_schema(s, ds, schema, "tester", "synthetic test schema")


def upload(engine, settings, registry, dataset_id, name, data, day=DAY, **confirm):
    with session_scope(engine) as s:
        res = inspect_upload(s, settings, registry, filename=name, data=data, dataset_id=dataset_id,
                             source_system=SOURCE_OF[dataset_id], reporting_date=day, sheet=None, header_row=1, actor="tester")
    if not res.get("can_confirm"):
        return res, None
    with session_scope(engine) as s:
        up = confirm_upload(s, settings, registry, token=res["token"], actor="tester",
                            acknowledge_review=True, **confirm)
        return res, up.upload_id


def load_day(engine, settings, registry, day=DAY, variant=0):
    files = build_dataset_files(day, variant)
    for ds in MASTER_ORDER + DAILY_ORDER:
        name, data = files[ds]
        res, uid = upload(engine, settings, registry, ds, name, data, day, supersede=True)
        assert uid, (ds, res)


# ------------------------------------------------------------------ inspection
@pytest.mark.parametrize("name,data,msg", [
    ("a.csv", b"", "empty"),
    ("a.zip", b"PK\x03\x04xx", "Archive"),
    ("a.xlsm", b"PK\x03\x04xx", "Macro"),
    ("a.exe", b"MZ", "Unsupported"),
    ("a.xlsx", bytes.fromhex("D0CF11E0A1B11AE1") + b"x" * 10, "password"),
    ("a.xlsx", b"not a zip", "signature"),
    ("a.csv", b"PK\x03\x04binary", "binary"),
])
def test_inspector_rejects_bad_files(name, data, msg):
    res = inspect_file(name, data, EXT, MB)
    assert not res.ok and msg.lower() in res.errors[0].lower()


def test_inspector_size_limit_and_macro_payload():
    assert "limit" in inspect_file("a.csv", b"x" * (MB + 1), EXT, MB).errors[0]
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("[Content_Types].xml", "<x/>")
        zf.writestr("xl/workbook.xml", "<x/>")
        zf.writestr("xl/vbaProject.bin", "evil")
    assert "macros" in inspect_file("a.xlsx", buf.getvalue(), EXT, MB).errors[0]


def test_safe_filename_strips_paths():
    assert safe_filename("..\\..\\etc/passwd") == "passwd"
    assert safe_filename("bad:name?.csv") == "bad_name_.csv"


def test_xlsx_reader_uses_cached_values_and_iso_dates():
    wb = Workbook()
    ws = wb.active
    ws.append(["Emp Code", "Date", "Calc"])
    ws.append(["E1", date(2026, 11, 13), "=1+1"])
    buf = io.BytesIO()
    wb.save(buf)
    t = read_table(buf.getvalue(), "xlsx")
    assert t.columns == ["Emp Code", "Date", "Calc"]
    assert t.rows[0]["Date"] == "2026-11-13"
    assert t.rows[0]["Calc"] in ("", "=1+1")   # formula never evaluated


# ------------------------------------------------------------------ validation
def _table(csv_text: str):
    return read_table(csv_text.encode(), "csv")


def test_validation_row_level_issues():
    schema = SCHEMAS["HRMS_ATTENDANCE"]
    t = _table("Emp Code,Date,Status,In,Out,Extra\n"
               "E1,13-11-2026,Present,09:00,18:00,x\n"
               "E1,13-11-2026,Present,09:00,18:00,x\n"        # exact duplicate -> ignored
               ",13-11-2026,Present,,,\n"                     # missing id
               "E2,31-02-2026,Present,,,\n"                   # invalid date
               "E3,12-11-2026,Present,,,\n"                   # wrong period
               "E4,13-11-2026,Gone fishing,,,\n"              # unmapped value (warning)
               "E4,13-11-2026,Present,,,\n"                   # duplicate business key
               ",,,,,\n")                                    # empty row
    r = validate_table(t, "HRMS_ATTENDANCE", schema, DAY, daily=True)
    codes = {i.code for i in r.issues}
    assert {"UNEXPECTED_COLUMN", "DUPLICATE_ROW", "MISSING_VALUE", "INVALID_DATE", "PERIOD_MISMATCH",
            "UNMAPPED_VALUE", "DUPLICATE_KEY", "EMPTY_ROW"} <= codes
    assert r.valid_rows == 2 and r.invalid_rows == 4 and r.duplicate_rows == 1 and r.empty_rows == 1
    assert r.status is ValidationStatus.REQUIRES_REVIEW
    unmapped = next(row for row in r.typed_rows if row.values["source_employee_id"] == "E4")
    assert unmapped.values["source_status_mapped"] is None   # never guessed


def test_validation_rejects_missing_columns_and_all_invalid():
    schema = SCHEMAS["HRMS_ATTENDANCE"]
    r = validate_table(_table("Emp Code,Date\nE1,13-11-2026\n"), "HRMS_ATTENDANCE", schema, DAY, True)
    assert r.status is ValidationStatus.REJECTED and any(i.code == "MISSING_COLUMN" for i in r.issues)
    r = validate_table(_table("Emp Code,Date,Status,In,Out\n,bad,,,\n"), "HRMS_ATTENDANCE", schema, DAY, True)
    assert r.status is ValidationStatus.REJECTED


def test_schema_definition_rules(engine):
    bad = SchemaDefinition(columns={"A": "attendance_date"})
    assert any("source_employee_id" in p for p in bad.validate_for("HRMS_ATTENDANCE"))
    bad_map = SchemaDefinition(columns={"A": "source_employee_id", "B": "attendance_date", "C": "source_status"},
                               value_maps={"source_status": {"X": "ON_HOLIDAY_IN_GOA"}})
    assert any("unknown values" in p for p in bad_map.validate_for("HRMS_ATTENDANCE"))
    with session_scope(engine) as s, pytest.raises(SchemaError):
        save_schema(s, "HRMS_ATTENDANCE", bad, "tester")


def test_schema_versions(engine):
    with session_scope(engine) as s:
        save_schema(s, "HRMS_ATTENDANCE", SCHEMAS["HRMS_ATTENDANCE"], "a")
        save_schema(s, "HRMS_ATTENDANCE", SCHEMAS["HRMS_ATTENDANCE"], "b")
    with session_scope(engine) as s:
        active = get_active_schema(s, "HRMS_ATTENDANCE")
        assert active.version == 2 and active.created_by == "b"


# ------------------------------------------------------------------ upload lifecycle
def test_upload_without_schema_is_discovery_only(engine, settings, registry):
    files = build_dataset_files(DAY)
    res, uid = upload(engine, settings, registry, "HRMS_ATTENDANCE", *files["HRMS_ATTENDANCE"])
    assert uid is None and res["schema_defined"] is False and res["can_confirm"] is False
    assert {p["column"] for p in res["profile"]} == {"Emp Code", "Date", "Status", "In", "Out"}
    with session_scope(engine) as s, pytest.raises(UploadError, match="no approved column schema"):
        confirm_upload(s, settings, registry, token=res["token"], actor="x")


def test_wrong_source_system_rejected(engine, settings, registry):
    with session_scope(engine) as s, pytest.raises(UploadError, match="comes from"):
        inspect_upload(s, settings, registry, filename="a.csv", data=b"a\n1", dataset_id="HRMS_ATTENDANCE",
                       source_system="BIZOM", reporting_date=DAY, sheet=None, header_row=1, actor="x")


def test_full_upload_archives_raw_and_standardizes(engine, settings, registry):
    define_all(engine)
    load_day(engine, settings, registry)
    with session_scope(engine) as s:
        ups = list(s.scalars(select(UploadRegistry)))
        assert len(ups) == 7 and all(u.status == "READY_FOR_PROCESSING" for u in ups)
        for u in ups:
            assert os.path.isfile(u.stored_path) and not os.access(u.stored_path, os.W_OK)   # read-only raw copy
        assert s.scalar(select(func.count()).select_from(UploadRow)) > 0
        assert s.scalar(select(func.count()).select_from(DimEmployee)) == 8
        assert s.scalar(select(func.count()).select_from(DimDepartment)) == 3
        assert s.scalar(select(func.count()).select_from(SourceAttendance)) == 10
        # Leave ranges expanded; approval mapped, pending stays pending.
        leaves = {l.source_employee_id: l.approval_status for l in s.scalars(select(LeaveRecordRow))}
        assert leaves == {"TEST-0003": "APPROVED", "TEST-0005": "PENDING"}
        # HRMS codes verified by exact match; Bizom ids need review, with name suggestions only.
        maps = {(m.source_system, m.source_employee_id): m for m in s.scalars(select(EmployeeSourceMapping))}
        assert maps[("POCKET_HRMS", "TEST-0001")].status == "VERIFIED"
        bz = maps[("BIZOM", "BZ-01")]
        assert bz.status == "PENDING" and bz.employee_key is None and bz.suggested_employee_key is not None
        assert maps[("BIZOM", "BZ-99")].suggested_employee_key is None


def test_duplicate_file_blocked_then_controlled_reprocess(engine, settings, registry):
    define_all(engine)
    name, data = build_dataset_files(DAY)["DEPARTMENT_MASTER"]
    _, first = upload(engine, settings, registry, "DEPARTMENT_MASTER", name, data)
    with session_scope(engine) as s:
        res = inspect_upload(s, settings, registry, filename=name, data=data, dataset_id="DEPARTMENT_MASTER",
                             source_system="HR", reporting_date=DAY, sheet=None, header_row=1, actor="t")
    assert res["duplicate_of"]["upload_id"] == first
    with session_scope(engine) as s, pytest.raises(UploadError, match="already uploaded"):
        confirm_upload(s, settings, registry, token=res["token"], actor="t", acknowledge_review=True)
    with session_scope(engine) as s, pytest.raises(UploadError, match="not authorised"):
        confirm_upload(s, settings, registry, token=res["token"], actor="t", reprocess=True)
    with session_scope(engine) as s:
        up = confirm_upload(s, settings, registry, token=res["token"], actor="t", reprocess=True, can_reprocess=True)
        assert up.reprocess_of == first
    with session_scope(engine) as s:
        old = s.get(UploadRegistry, first)
        assert old.is_current is False and old.superseded_by is not None


def test_corrected_file_requires_explicit_supersede(engine, settings, registry):
    define_all(engine)
    load_day(engine, settings, registry)
    name, data = build_dataset_files(DAY, variant=1)["HRMS_ATTENDANCE"]
    with session_scope(engine) as s:
        res = inspect_upload(s, settings, registry, filename=name, data=data, dataset_id="HRMS_ATTENDANCE",
                             source_system="POCKET_HRMS", reporting_date=DAY, sheet=None, header_row=1, actor="t")
    assert res["current_upload"]
    with session_scope(engine) as s, pytest.raises(UploadError, match="supersedes"):
        confirm_upload(s, settings, registry, token=res["token"], actor="t", acknowledge_review=True)
    with session_scope(engine) as s:
        confirm_upload(s, settings, registry, token=res["token"], actor="t", acknowledge_review=True, supersede=True)
    with session_scope(engine) as s:
        current = s.scalars(select(UploadRegistry).where(UploadRegistry.dataset_id == "HRMS_ATTENDANCE",
                                                         UploadRegistry.is_current.is_(True))).all()
        assert len(current) == 1


def test_review_acknowledgement_and_exceptions_export(engine, settings, registry):
    define_all(engine)
    data = b"Emp Code,Date,Status,In,Out\nTEST-0001,13-11-2026,Present,,\nTEST-0002,bad,Present,,\n"
    with session_scope(engine) as s:
        res = inspect_upload(s, settings, registry, filename="h.csv", data=data, dataset_id="HRMS_ATTENDANCE",
                             source_system="POCKET_HRMS", reporting_date=DAY, sheet=None, header_row=1, actor="t")
    assert res["validation"]["status"] == "REQUIRES_REVIEW"
    with session_scope(engine) as s, pytest.raises(UploadError, match="Review"):
        confirm_upload(s, settings, registry, token=res["token"], actor="t")
    with session_scope(engine) as s:
        up = confirm_upload(s, settings, registry, token=res["token"], actor="t", acknowledge_review=True)
        uid = up.upload_id
    with session_scope(engine) as s:
        assert s.scalar(select(func.count()).select_from(ValidationIssue).where(ValidationIssue.upload_id == uid)) == 1
        assert "INVALID_DATE" in exceptions_csv(s, uid)


def test_department_change_keeps_history(engine, settings, registry):
    define_all(engine)
    files = build_dataset_files(DAY)
    upload(engine, settings, registry, "HRMS_EMPLOYEE_MASTER", *files["HRMS_EMPLOYEE_MASTER"])
    moved = files["HRMS_EMPLOYEE_MASTER"][1].replace(b"TEST-0001,Asha Test,SALES", b"TEST-0001,Asha Test,FIN")
    upload(engine, settings, registry, "HRMS_EMPLOYEE_MASTER", "employees2.csv", moved, day=date(2026, 12, 1), supersede=True)
    with session_scope(engine) as s:
        emp = s.scalar(select(DimEmployee).where(DimEmployee.employee_code == "TEST-0001"))
        hist = list(s.scalars(select(EmployeeOrgHistory).where(EmployeeOrgHistory.employee_key == emp.employee_key)
                              .order_by(EmployeeOrgHistory.effective_from)))
        assert [(h.department_code, h.effective_to) for h in hist] == [("SALES", date(2026, 11, 30)), ("FIN", None)]


def test_manual_mapping_resolution(engine, settings, registry):
    define_all(engine)
    load_day(engine, settings, registry)
    with session_scope(engine) as s:
        m = s.scalar(select(EmployeeSourceMapping).where(EmployeeSourceMapping.source_employee_id == "BZ-01"))
        emp = s.scalar(select(DimEmployee).where(DimEmployee.employee_code == "TEST-0001"))
        with pytest.raises(ValueError):
            resolve_mapping(s, m.mapping_id, None, "hr")
        resolve_mapping(s, m.mapping_id, emp.employee_key, "hr")
        assert m.status == "VERIFIED" and m.method == "MANUAL"
