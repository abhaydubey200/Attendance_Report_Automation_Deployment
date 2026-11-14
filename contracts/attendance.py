"""Attendance contract and status vocabulary (PRD 6.2 / 8.2 / 9.2)."""

from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum

from pydantic import field_validator

from contracts.base import SourcedRecord, require_aware


class AttendanceStatus(StrEnum):
    PRESENT = "PRESENT"
    ABSENT = "ABSENT"
    APPROVED_LEAVE = "APPROVED_LEAVE"
    HALF_DAY = "HALF_DAY"
    WORK_FROM_HOME = "WORK_FROM_HOME"
    WEEKLY_OFF = "WEEKLY_OFF"
    HOLIDAY = "HOLIDAY"
    MISSING_PUNCH = "MISSING_PUNCH"
    PENDING_APPROVAL = "PENDING_APPROVAL"
    UNRESOLVED = "UNRESOLVED"


class RecordStatus(StrEnum):
    """Whether a calculated value rests on approved rules."""

    PROVISIONAL = "PROVISIONAL"
    OFFICIAL = "OFFICIAL"
    SUPERSEDED = "SUPERSEDED"


class ReconciliationCategory(StrEnum):
    MATCHED = "MATCHED"
    BIZOM_ONLY = "BIZOM_ONLY"
    HRMS_ONLY = "HRMS_ONLY"
    STATUS_CONFLICT = "STATUS_CONFLICT"
    TIME_CONFLICT = "TIME_CONFLICT"
    EMPLOYEE_MAPPING_MISSING = "EMPLOYEE_MAPPING_MISSING"
    DUPLICATE_RECORD = "DUPLICATE_RECORD"
    LEAVE_CONFLICT = "LEAVE_CONFLICT"
    PENDING_REVIEW = "PENDING_REVIEW"
    RESOLVED = "RESOLVED"


class AttendanceRecord(SourcedRecord):
    """A source-reported attendance row after normalization (not the final daily fact)."""

    employee_code: str
    employee_id: str | None = None
    attendance_date: date
    source_status: str | None = None                 # raw status text as reported by the source
    attendance_status: AttendanceStatus | None = None
    first_in_time: datetime | None = None
    last_out_time: datetime | None = None
    reporting_run_id: str | None = None
    record_status: RecordStatus = RecordStatus.PROVISIONAL

    # Out-before-in is deliberately NOT rejected: overnight shifts and invalid sequences
    # are an engine/reconciliation concern (PRD 8.5), not a contract violation.
    _aware = field_validator("first_in_time", "last_out_time")(require_aware)
