"""Phases 5, 6, 8: engine classification, idempotent runs, reconciliation, exceptions, reports."""

from __future__ import annotations

import io
import json
from datetime import date, datetime

import pytest
from openpyxl import load_workbook
from sqlalchemy import func, select

from contracts.attendance import AttendanceStatus as S
from core.config import AttendanceCalculationRules, AttendanceRules, SourceAuthority, load_attendance_rules, load_source_authority
from core.timeutils import IST
from database.connection import session_scope
from database.models.attendance import AttendanceException, AttendanceReconciliation, FactAttendanceDaily, ProcessingRun
from database.models.audit import ExceptionResolutionLog, ProcessingLog
from database.models.hr import DimEmployee, EmployeeSourceMapping
from database.models.reporting import ReportRegistry
from data_engine import exception_manager, kpi_calculator
from data_engine.attendance_processor import DayInputs, SourceView, classify
from data_engine.employee_mapper import resolve_mapping
from orchestration.pipeline import PipelineError, approve_run, resume_run, start_run
from reporting.report_manager import can_view, decide, open_report
from security.permissions import Principal
from tests.integration.test_ingestion import DAY, define_all, load_day, registry  # noqa: F401  (fixture)

RULES = load_attendance_rules()
AUTH = load_source_authority()


def P(*perms, depts=()):
    return Principal(1, "hr.tester", "HR Tester", permissions=frozenset(perms), departments=frozenset(depts))


ALL = P("REPORT_VIEW_HOD", "REPORT_VIEW_DIRECTORS", "REPORT_GENERATE", "ATTENDANCE_VIEW_ALL_DEPARTMENTS", "REPORT_APPROVE")


# ------------------------------------------------------------------ classification (pure)
def V(status=None, raw="x"):
    return SourceView(present=True, status=status, raw=raw)


@pytest.mark.parametrize("inputs,expected", [
    (DayInputs(hrms=V("PRESENT"), bizom=V("PRESENT")), S.PRESENT),
    (DayInputs(hrms=V("ABSENT"), bizom=V("PRESENT")), S.UNRESOLVED),            # conflict, no approved authority
    (DayInputs(hrms=V(None, "??")), S.UNRESOLVED),                               # unmapped source value
    (DayInputs(leave_approval="APPROVED", leave_portion="FULL_DAY", hrms=V("ABSENT")), S.APPROVED_LEAVE),
    (DayInputs(leave_approval="APPROVED", leave_portion="FIRST_HALF"), S.HALF_DAY),
    (DayInputs(leave_approval="PENDING"), S.PENDING_APPROVAL),                   # pending never becomes approved
    (DayInputs(holiday="Diwali"), S.HOLIDAY),
    (DayInputs(holiday="Diwali", hrms=V("PRESENT")), S.PRESENT),
    (DayInputs(punches=[(datetime(2026, 11, 13, 9, tzinfo=IST), "IN")]), S.MISSING_PUNCH),
    (DayInputs(punches=[(datetime(2026, 11, 13, 9, tzinfo=IST), "IN"), (datetime(2026, 11, 13, 18, tzinfo=IST), "OUT")]), S.UNRESOLVED),
    (DayInputs(), S.UNRESOLVED),                                                  # no record; rule pending
    (DayInputs(adjustment=(7, "PRESENT"), hrms=V("ABSENT")), S.PRESENT),
])
def test_classification(inputs, expected):
    assert classify(inputs, RULES, AUTH).status == expected


def test_conflict_uses_approved_authority_and_no_record_rule():
    auth = SourceAuthority.model_validate({"approval_status": "APPROVED", "domains": {
        "OFFICE_ATTENDANCE": {"authoritative_source": "POCKET_HRMS"}}})
    assert classify(DayInputs(hrms=V("ABSENT"), bizom=V("PRESENT")), RULES, auth).status == S.ABSENT
    rules = RULES.model_copy(update={"calculation": RULES.calculation.model_copy(update={"no_record_status": S.ABSENT})})
    assert classify(DayInputs(), rules, AUTH).status == S.ABSENT


def test_percentages_only_with_approved_rules():
    statuses = ["PRESENT"] * 6 + ["ABSENT"] * 2 + ["HALF_DAY"] * 2 + ["APPROVED_LEAVE"] + ["WEEKLY_OFF"]
    assert kpi_calculator.summarize(statuses, RULES)["attendance_pct"] is None
    approved = AttendanceRules(
        rule_version="1.0.0", approval_status="APPROVED", approved_by="HR", approved_on="2026-11-01", timezone="Asia/Kolkata",
        statuses=RULES.statuses, calculation=AttendanceCalculationRules(
            half_day_equivalent=0.5, wfh_counts_as_present=True, approved_leave_in_denominator=False,
            include_weekly_off_in_denominator=False, include_holidays_in_denominator=False))
    s = kpi_calculator.summarize(statuses, approved)
    assert s["attendance_pct"] == 70.0 and s["absenteeism_pct"] == 20.0   # (6 + 2*0.5)/10, 2/10


# ------------------------------------------------------------------ pipeline
@pytest.fixture
def loaded(engine, settings, registry):  # noqa: F811
    define_all(engine)
    load_day(engine, settings, registry)
    return engine


def facts_by_code(engine, run_id):
    with session_scope(engine) as s:
        return {e.employee_code: f for f, e in s.execute(
            select(FactAttendanceDaily, DimEmployee).join(DimEmployee, DimEmployee.employee_key == FactAttendanceDaily.employee_key)
            .where(FactAttendanceDaily.run_id == run_id))}


def test_run_end_to_end(loaded, settings):
    res = start_run(loaded, settings, DAY, "tester")
    assert res.created and res.state == "READY_FOR_REVIEW", res
    f = facts_by_code(loaded, res.run_id)
    assert len(f) == 8 and all(x.record_status == "PROVISIONAL" for x in f.values())
    assert f["TEST-0001"].final_status == "PRESENT"
    assert f["TEST-0002"].final_status == "ABSENT"            # Bizom BZ-02 unmapped yet -> HRMS only
    assert f["TEST-0003"].final_status == "APPROVED_LEAVE"
    assert f["TEST-0004"].final_status == "WORK_FROM_HOME"
    assert f["TEST-0005"].final_status == "PENDING_APPROVAL"
    assert f["TEST-0006"].final_status == "HALF_DAY"
    assert f["TEST-0008"].final_status == "PRESENT"
    assert f["TEST-0001"].first_in is not None and f["TEST-0001"].punch_count == 2
    with session_scope(loaded) as s:
        run = s.get(ProcessingRun, res.run_id)
        assert run.is_current and run.ai_status == "DISABLED"
        stats = json.loads(run.stats)
        assert stats["kpis"]["attendance_pct"] is None and stats["kpis"]["percentages_status"] == "PENDING_HR_APPROVAL"
        stages = [l.stage for l in s.scalars(select(ProcessingLog).where(ProcessingLog.run_id == res.run_id))]
        assert stages[:5] == ["UPLOADING", "VALIDATING", "PROCESSING", "RECONCILING", "GENERATING_REPORTS"]
        cats = {r.category for r in s.scalars(select(AttendanceReconciliation).where(AttendanceReconciliation.run_id == res.run_id))}
        assert "EMPLOYEE_MAPPING_MISSING" in cats and "HRMS_ONLY" in cats


def test_identical_inputs_do_not_duplicate(loaded, settings):
    first = start_run(loaded, settings, DAY, "tester")
    again = start_run(loaded, settings, DAY, "tester")
    assert not again.created and again.run_id == first.run_id
    with session_scope(loaded) as s:
        assert s.scalar(select(func.count()).select_from(ProcessingRun)) == 1


def test_mapping_change_creates_new_version_and_reconciles(loaded, settings):
    first = start_run(loaded, settings, DAY, "tester")
    with session_scope(loaded) as s:
        for bz, code in (("BZ-01", "TEST-0001"), ("BZ-02", "TEST-0002"), ("BZ-03", "TEST-0003")):
            m = s.scalar(select(EmployeeSourceMapping).where(EmployeeSourceMapping.source_employee_id == bz))
            emp = s.scalar(select(DimEmployee).where(DimEmployee.employee_code == code))
            resolve_mapping(s, m.mapping_id, emp.employee_key, "hr")
    second = start_run(loaded, settings, DAY, "tester")
    assert second.created and second.run_ref.endswith("v2")
    f = facts_by_code(loaded, second.run_id)
    assert f["TEST-0002"].final_status == "UNRESOLVED"           # HRMS Absent vs Bizom Present
    with session_scope(loaded) as s:
        assert not s.get(ProcessingRun, first.run_id).is_current and s.get(ProcessingRun, second.run_id).is_current
        cats = [r.category for r in s.scalars(select(AttendanceReconciliation).where(AttendanceReconciliation.run_id == second.run_id))]
        assert "STATUS_CONFLICT" in cats and "MATCHED" in cats and "LEAVE_CONFLICT" in cats
        # Open exceptions of v1 were superseded, not deleted.
        assert {e.status for e in s.scalars(select(AttendanceException).where(AttendanceException.run_id == first.run_id))} == {"SUPERSEDED"}


def test_exception_workflow_adjustment_applies_next_run(loaded, settings):
    test_mapping_change_creates_new_version_and_reconciles(loaded, settings)
    hr = P("ATTENDANCE_VIEW_ALL_DEPARTMENTS")
    hr = Principal(1, "hr.reviewer", "HR", permissions=hr.permissions)
    with session_scope(loaded) as s:
        exc = s.scalar(select(AttendanceException).where(AttendanceException.category == "STATUS_CONFLICT",
                                                         AttendanceException.status == "PENDING_REVIEW"))
        original = exc.source_values
        with pytest.raises(exception_manager.ExceptionWorkflowError):
            exception_manager.resolve(s, exc.exception_id, hr, decision="ADJUST", comment="x", adjusted_status="ABSENT")
        exception_manager.assign(s, exc.exception_id, "hr.reviewer", hr)
        exception_manager.start_review(s, exc.exception_id, hr)
        with pytest.raises(exception_manager.ExceptionWorkflowError, match="comment"):
            exception_manager.resolve(s, exc.exception_id, hr, decision="ADJUST", comment=" ", adjusted_status="ABSENT")
        exception_manager.resolve(s, exc.exception_id, hr, decision="ADJUST", comment="Confirmed with HOD", adjusted_status="ABSENT")
        eid = exc.exception_id
    with session_scope(loaded) as s:
        exc = s.get(AttendanceException, eid)
        assert exc.status == "RESOLVED" and exc.source_values == original
        trail = [l.to_status for l in s.scalars(select(ExceptionResolutionLog).where(ExceptionResolutionLog.exception_id == eid))]
        assert trail == ["PENDING_REVIEW", "ASSIGNED", "UNDER_REVIEW", "RESOLVED"]
    third = start_run(loaded, settings, DAY, "tester")
    f = facts_by_code(loaded, third.run_id)
    assert f["TEST-0002"].final_status == "ABSENT" and "exception" in f["TEST-0002"].reason


def test_hod_scope_on_exceptions(loaded, settings):
    test_mapping_change_creates_new_version_and_reconciles(loaded, settings)
    fin_hod = Principal(5, "hod.fin", "HOD", permissions=frozenset({"RECONCILIATION_RESOLVE"}), departments=frozenset({"FIN"}))
    with session_scope(loaded) as s:
        sales_exc = s.scalar(select(AttendanceException).where(AttendanceException.department_code == "SALES",
                                                               AttendanceException.status == "PENDING_REVIEW"))
        with pytest.raises(LookupError):
            exception_manager.assign(s, sales_exc.exception_id, "x", fin_hod)


def test_failed_run_and_resume(loaded, settings, monkeypatch):
    import reporting.report_manager as rm

    def boom(*a, **k):
        raise RuntimeError("disk full")

    monkeypatch.setattr(rm, "generate_for_run", boom)
    res = start_run(loaded, settings, DAY, "tester")
    assert res.state == "FAILED"
    with session_scope(loaded) as s:
        assert "disk full" in s.get(ProcessingRun, res.run_id).error
        assert s.scalar(select(func.count()).select_from(FactAttendanceDaily).where(FactAttendanceDaily.run_id == res.run_id)) == 8
    monkeypatch.undo()
    resumed = resume_run(loaded, settings, res.run_id, "tester")
    assert resumed.state == "READY_FOR_REVIEW"
    with session_scope(loaded) as s:   # facts not recomputed when resuming at the report stage
        assert s.scalar(select(func.count()).select_from(FactAttendanceDaily).where(FactAttendanceDaily.run_id == res.run_id)) == 8
    with pytest.raises(PipelineError):
        resume_run(loaded, settings, res.run_id, "tester")


def test_run_without_employee_master_fails(engine, settings):
    res = start_run(engine, settings, DAY, "tester")
    assert res.state == "FAILED"


# ------------------------------------------------------------------ reports
def test_reports_generated_scoped_and_approvable(loaded, settings):
    res = start_run(loaded, settings, DAY, "tester")
    with session_scope(loaded) as s:
        reports = list(s.scalars(select(ReportRegistry).where(ReportRegistry.run_id == res.run_id)))
        kinds = {(r.report_type, r.department_code, r.file_format) for r in reports}
        assert ("HOD", "SALES", "XLSX") in kinds and ("DIRECTORS", None, "HTML") in kinds and ("HR_ADMIN", None, "XLSX") in kinds
        assert all(r.provisional for r in reports)
        sales = next(r for r in reports if r.report_type == "HOD" and r.department_code == "SALES" and r.file_format == "XLSX")
        directors = next(r for r in reports if r.report_type == "DIRECTORS" and r.file_format == "XLSX")
        hod_fin = Principal(9, "hod.fin", "HOD", permissions=frozenset({"REPORT_VIEW_HOD"}), departments=frozenset({"FIN"}))
        assert not can_view(hod_fin, sales) and not can_view(hod_fin, directors)
        with pytest.raises(LookupError):
            open_report(s, settings, hod_fin, sales.report_id)
        _, content = open_report(s, settings, ALL, sales.report_id)
        wb = load_workbook(io.BytesIO(content))
        assert wb.sheetnames == ["Executive Summary", "Attendance Details", "Absent Employees", "Leave Details",
                                 "Missing Punch", "Reconciliation", "Data Quality"]
        text = " ".join(str(c.value) for row in wb["Attendance Details"].iter_rows() for c in row if c.value)
        assert "PROVISIONAL" in text and "TEST-0001" in text and "TEST-0004" not in text   # FIN employee excluded
        _, dcontent = open_report(s, settings, ALL, directors.report_id)
        dwb = load_workbook(io.BytesIO(dcontent))
        assert "AI Insights" in dwb.sheetnames
        dtext = " ".join(str(c.value) for ws in dwb for row in ws.iter_rows() for c in row if c.value)
        assert "TEST-00" not in dtext and "Pending HR approval" in dtext                  # no employee-level data
        decide(s, sales.report_id, ALL, "APPROVED", "ok")
        with pytest.raises(Exception, match="already"):
            decide(s, sales.report_id, ALL, "REJECTED", None)
    assert approve_run(loaded, res.run_id, "hr") == "APPROVED"


def test_tampered_report_detected(loaded, settings):
    import os
    import stat

    res = start_run(loaded, settings, DAY, "tester")
    with session_scope(loaded) as s:
        r = s.scalar(select(ReportRegistry).where(ReportRegistry.run_id == res.run_id, ReportRegistry.file_format == "HTML"))
        os.chmod(r.file_path, stat.S_IWRITE | stat.S_IREAD)
        with open(r.file_path, "ab") as fh:
            fh.write(b"tampered")
        with pytest.raises(Exception, match="checksum"):
            open_report(s, settings, ALL, r.report_id)
