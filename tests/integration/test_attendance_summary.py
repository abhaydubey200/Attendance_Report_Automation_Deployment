"""Pocket HRMS AttendanceSummary: reader, labels, exclusions, standardization, engine, reports.
Synthetic workbook in the real layout (no real employee data)."""

from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy import func, select

from database.connection import session_scope
from database.models.attendance import AttendancePunch, FactAttendanceDaily, ProcessingRun, SourceAttendance
from database.models.hr import DimDepartment, DimEmployee, EmployeeSourceMapping
from database.models.reporting import ReportRegistry
from demo.synthetic import build_summary_xlsx
from ingestion.dataset_registry import load_dataset_registry
from ingestion.file_reader import ReadError, read_raw
from ingestion.reshapers import reshape_attendance_summary
from ingestion.schema_definition import SchemaDefinition
from ingestion.schema_service import get_active_schema, save_schema
from ingestion.upload_manager import confirm_upload, inspect_upload
from orchestration.pipeline import expected_missing, start_run

DAY = date(2026, 11, 13)


def _table(day=DAY):
    rows, sheets = read_raw(build_summary_xlsx(day), "xlsx")
    return reshape_attendance_summary(rows, 1, sheets)


def test_reshaper_pairs_rows_and_labels_facts_only():
    t = _table()
    by = {r["Code"]: r for r in t.rows}
    assert len(t.rows) == 9                                   # 18 sheet rows -> 9 employees
    assert "Remarks" not in t.columns                         # free text dropped (data minimisation)
    assert by["HO9003"]["Derived Status"] == "LEAVE:PL" and by["HO9003"]["Day"] == "Full Day"
    assert by["SL90003"]["Derived Status"] == "LEAVE:LD"
    assert by["RK90002"]["Derived Status"] == "PUNCH_SINGLE" and by["RK90002"]["In Time"] == "09:12"
    assert by["SL90001"]["Derived Status"] == "NO_PUNCH_NO_SHIFT"
    assert by["HO9001"]["Name"] == "Aarti Synth"               # trailing/double spaces normalised
    assert t.row_numbers[0] == 6                              # source row of the first record


def test_reshaper_requires_the_report_header():
    with pytest.raises(ReadError, match="Header row not found"):
        reshape_attendance_summary([["a", "b"], ["1", "2"]])


def _seed(engine):
    with session_scope(engine) as s:
        d = load_dataset_registry().get("HRMS_ATTENDANCE_SUMMARY")
        save_schema(s, d.dataset_id, SchemaDefinition.model_validate(d.seed_schema["definition"]), "test-seed", d.seed_schema["notes"])


def _upload(engine, settings, data, day=DAY, **confirm):
    registry = load_dataset_registry()
    with session_scope(engine) as s:
        res = inspect_upload(s, settings, registry, filename="AttendanceSummary.xlsx", data=data,
                             dataset_id="HRMS_ATTENDANCE_SUMMARY", source_system="POCKET_HRMS", reporting_date=day,
                             sheet=None, header_row=1, actor="t")
    assert res["can_confirm"], res
    with session_scope(engine) as s:
        up = confirm_upload(s, settings, registry, token=res["token"], actor="t", acknowledge_review=True, **confirm)
        return res, up.upload_id


def test_init_db_seeds_schema_once(isolated_env):
    import main
    from core.config import get_settings
    from database.connection import create_db_engine

    assert main.main(["init-db"]) == 0
    engine = create_db_engine(get_settings())
    with session_scope(engine) as s:
        assert get_active_schema(s, "HRMS_ATTENDANCE_SUMMARY").created_by == "seed:datasets.yaml"
    assert main.main(["init-db"]) == 0
    with session_scope(engine) as s:
        assert get_active_schema(s, "HRMS_ATTENDANCE_SUMMARY").version == 1   # never re-seeded over an existing schema


def test_upload_creates_employees_categories_and_records(engine, settings):
    _seed(engine)
    res, uid = _upload(engine, settings, build_summary_xlsx(DAY))
    v = res["validation"]
    assert v["total_rows"] == 9 and v["invalid_rows"] == 0
    assert any(i["code"] == "UNMAPPED_VALUE" and "NO_PUNCH" in i["message"] for i in v["issues"])   # one aggregated warning
    with session_scope(engine) as s:
        assert s.scalar(select(func.count()).select_from(DimEmployee)) == 9
        assert {d.department_code for d in s.scalars(select(DimDepartment))} == {"HEAD_OFFICE", "PLANT", "SALES"}
        assert all(m.status == "VERIFIED" for m in s.scalars(select(EmployeeSourceMapping)))
        att = {a.source_employee_id: a for a in s.scalars(select(SourceAttendance))}
        assert att["HO9003"].mapped_status == "APPROVED_LEAVE" and att["SL90003"].mapped_status is None
        assert s.scalar(select(func.count()).select_from(AttendancePunch).where(AttendancePunch.source_employee_id == "RK90002")) == 1


def test_exclusion_list_skips_test_codes_without_forcing_review(engine, settings):
    d = load_dataset_registry().get("HRMS_ATTENDANCE_SUMMARY")
    definition = SchemaDefinition.model_validate({**d.seed_schema["definition"], "exclude_codes": ["DUMMY"],
                                                  "value_maps": {"source_status": {
                                                      "PUNCH_IN_OUT": "PRESENT", "PUNCH_SINGLE": "MISSING_PUNCH",
                                                      "LEAVE:PL": "APPROVED_LEAVE", "LEAVE:LD": "PRESENT",
                                                      "NO_PUNCH": "ABSENT", "NO_PUNCH_NO_SHIFT": "ABSENT"}}})
    with session_scope(engine) as s:
        save_schema(s, "HRMS_ATTENDANCE_SUMMARY", definition, "hr")
    res, _ = _upload(engine, settings, build_summary_xlsx(DAY))
    v = res["validation"]
    assert v["total_rows"] == 8 and v["status"] == "VALID"
    assert v["issues_by_code"] == {"EXCLUDED_CODE": 1}
    with session_scope(engine) as s:
        assert s.scalar(select(DimEmployee).where(DimEmployee.employee_code == "SLDUMMY9")) is None


def test_engine_run_with_summary_only(engine, settings):
    _seed(engine)
    _upload(engine, settings, build_summary_xlsx(DAY))
    res = start_run(engine, settings, DAY, "t")
    assert res.state == "READY_FOR_REVIEW"
    with session_scope(engine) as s:
        facts = {e.employee_code: f for f, e in s.execute(
            select(FactAttendanceDaily, DimEmployee).join(DimEmployee, DimEmployee.employee_key == FactAttendanceDaily.employee_key)
            .where(FactAttendanceDaily.run_id == res.run_id))}
        assert facts["HO9003"].final_status == "APPROVED_LEAVE"
        assert facts["RK90002"].final_status == "MISSING_PUNCH"
        assert facts["SL90001"].final_status == "UNRESOLVED"       # no punch: HR has not decided
        assert facts["SL90003"].final_status == "UNRESOLVED"       # LD: HR has not decided
        assert facts["HO9001"].department_code == "HEAD_OFFICE"
        import json
        assert json.loads(s.get(ProcessingRun, res.run_id).stats)["missing_datasets"] == []
        hods = {r.department_code for r in s.scalars(select(ReportRegistry).where(ReportRegistry.run_id == res.run_id,
                                                                                   ReportRegistry.report_type == "HOD"))}
        assert hods == {"HEAD_OFFICE", "PLANT", "SALES"}


def test_expected_missing(settings):
    assert expected_missing(settings, {"HRMS_ATTENDANCE_SUMMARY": [1]}) == []
    assert expected_missing(settings, {}) == ["HRMS_ATTENDANCE_SUMMARY"]
    # Separate exports instead of the summary: Bizom is off, so it is not expected.
    assert expected_missing(settings, {"HRMS_ATTENDANCE": [1]}) == ["HRMS_LEAVE", "HRMS_PUNCH"]


def test_csv_variant_of_the_report(engine, settings):
    """The same report saved as CSV is read the same way."""
    import csv
    import io

    from openpyxl import load_workbook

    wb = load_workbook(io.BytesIO(build_summary_xlsx(DAY)), read_only=True)
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    for row in wb.active.iter_rows(values_only=True):
        w.writerow(["" if c is None else c for c in row])
    rows, _ = read_raw(buf.getvalue().encode(), "csv")
    assert len(reshape_attendance_summary(rows).rows) == 9
