from __future__ import annotations

from datetime import date, datetime, timedelta

import pytest
from pydantic import ValidationError

from contracts.attendance import AttendanceRecord, AttendanceStatus, RecordStatus
from contracts.department import EmployeeOrgAssignment
from contracts.employee import EmployeeRecord
from contracts.leave import LeaveApprovalStatus, LeaveRecord
from contracts.processing import (
    ProcessingState,
    UploadState,
    validate_processing_transition,
    validate_upload_transition,
    TERMINAL_PROCESSING_STATES,
)
from contracts.punch import PunchEvent
from core.exceptions import InvalidStateTransition
from core.timeutils import IST

# Synthetic identifiers only -- never real employee data.
EMP = "TEST-0001"


def test_attendance_record_defaults_to_provisional():
    rec = AttendanceRecord(source_system="BIZOM", employee_code=EMP, attendance_date=date(2026, 11, 13))
    assert rec.record_status is RecordStatus.PROVISIONAL
    assert rec.attendance_status is None


def test_contracts_reject_unknown_fields():
    with pytest.raises(ValidationError):
        AttendanceRecord(source_system="BIZOM", employee_code=EMP, attendance_date=date(2026, 11, 13), foo=1)


def test_contracts_are_immutable():
    rec = AttendanceRecord(source_system="BIZOM", employee_code=EMP, attendance_date=date(2026, 11, 13))
    with pytest.raises(ValidationError):
        rec.employee_code = "X"


def test_naive_timestamps_rejected():
    with pytest.raises(ValidationError, match="timezone-aware"):
        PunchEvent(source_system="POCKET_HRMS", employee_code=EMP, punch_time=datetime(2026, 11, 13, 9, 0))
    ok = PunchEvent(source_system="POCKET_HRMS", employee_code=EMP, punch_time=datetime(2026, 11, 13, 9, 0, tzinfo=IST))
    assert ok.punch_time.tzinfo is not None


def test_out_before_in_is_not_a_contract_error():
    """Overnight shifts / bad sequences are an engine concern (PRD 8.5)."""
    t = datetime(2026, 11, 13, 22, 0, tzinfo=IST)
    AttendanceRecord(
        source_system="BIZOM", employee_code=EMP, attendance_date=date(2026, 11, 13),
        first_in_time=t, last_out_time=t - timedelta(hours=14),
    )


def test_unknown_source_system_rejected():
    with pytest.raises(ValidationError):
        AttendanceRecord(source_system="SAP", employee_code=EMP, attendance_date=date(2026, 11, 13))


@pytest.mark.parametrize("status", list(LeaveApprovalStatus))
def test_only_explicitly_approved_leave_is_approved(status):
    leave = LeaveRecord(source_system="POCKET_HRMS", employee_code=EMP, leave_date=date(2026, 11, 13), approval_status=status)
    assert leave.is_approved is (status is LeaveApprovalStatus.APPROVED)


def test_leave_defaults_to_unknown_not_approved():
    leave = LeaveRecord(source_system="POCKET_HRMS", employee_code=EMP, leave_date=date(2026, 11, 13))
    assert leave.approval_status is LeaveApprovalStatus.UNKNOWN and not leave.is_approved


def test_employee_exit_before_joining_rejected():
    with pytest.raises(ValidationError, match="exit_date"):
        EmployeeRecord(source_system="POCKET_HRMS", employee_code=EMP, joining_date=date(2026, 5, 1), exit_date=date(2026, 4, 1))


def test_org_assignment_effective_dating():
    a = EmployeeOrgAssignment(
        source_system="HR", employee_code=EMP, department_code="D1",
        effective_from=date(2026, 1, 1), effective_to=date(2026, 6, 30),
    )
    assert a.applies_on(date(2026, 6, 30)) and not a.applies_on(date(2026, 7, 1))


def test_attendance_statuses_match_prd():
    assert {s.value for s in AttendanceStatus} == {
        "PRESENT", "ABSENT", "APPROVED_LEAVE", "HALF_DAY", "WORK_FROM_HOME", "WEEKLY_OFF",
        "HOLIDAY", "MISSING_PUNCH", "PENDING_APPROVAL", "UNRESOLVED",
    }


def test_upload_lifecycle_happy_path_and_skips():
    sequence = list(UploadState)[:-1]  # all but REJECTED
    for current, nxt in zip(sequence, sequence[1:]):
        validate_upload_transition(current, nxt)
    # Cannot skip validation and confirmation (PRD 5.6).
    with pytest.raises(InvalidStateTransition):
        validate_upload_transition(UploadState.FILE_SELECTED, UploadState.READY_FOR_PROCESSING)
    with pytest.raises(InvalidStateTransition):
        validate_upload_transition(UploadState.PREVIEW, UploadState.RAW_FILE_ARCHIVE)


def test_processing_transitions():
    P = ProcessingState
    validate_processing_transition(P.AI_PROCESSING, P.AI_UNAVAILABLE)  # AI failure is not run failure
    validate_processing_transition(P.FAILED, P.GENERATING_REPORTS)     # resume from safe stage
    with pytest.raises(InvalidStateTransition):
        validate_processing_transition(P.AI_PROCESSING, P.FAILED)
    with pytest.raises(InvalidStateTransition):
        validate_processing_transition(P.READY_FOR_REVIEW, P.DISTRIBUTING)  # approval required
    assert TERMINAL_PROCESSING_STATES == {P.COMPLETED, P.CANCELLED}


def test_every_processing_state_has_transition_entry():
    from contracts.processing import PROCESSING_TRANSITIONS

    assert set(PROCESSING_TRANSITIONS) == set(ProcessingState)
