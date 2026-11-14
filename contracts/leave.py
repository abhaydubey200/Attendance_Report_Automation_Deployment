"""Leave contract (PRD 6.2 / 8.6)."""

from __future__ import annotations

from datetime import date
from enum import StrEnum

from contracts.base import SourcedRecord


class LeaveApprovalStatus(StrEnum):
    APPROVED = "APPROVED"
    PENDING = "PENDING"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"
    UNKNOWN = "UNKNOWN"     # source value not yet mapped -- never treated as approved


class LeaveDayPortion(StrEnum):
    FULL_DAY = "FULL_DAY"
    FIRST_HALF = "FIRST_HALF"
    SECOND_HALF = "SECOND_HALF"
    UNKNOWN = "UNKNOWN"


class LeaveRecord(SourcedRecord):
    employee_code: str
    employee_id: str | None = None
    leave_date: date
    leave_type: str | None = None
    source_approval_status: str | None = None
    approval_status: LeaveApprovalStatus = LeaveApprovalStatus.UNKNOWN
    day_portion: LeaveDayPortion = LeaveDayPortion.UNKNOWN

    @property
    def is_approved(self) -> bool:
        """Only explicitly approved leave counts as approved leave (PRD 8.6)."""
        return self.approval_status is LeaveApprovalStatus.APPROVED
