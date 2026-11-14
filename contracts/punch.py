"""Punch event contract (PRD 8.5). Every individual punch is preserved."""

from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum

from pydantic import field_validator

from contracts.base import SourcedRecord, require_aware


class PunchDirection(StrEnum):
    IN = "IN"
    OUT = "OUT"
    UNKNOWN = "UNKNOWN"


class PunchEvent(SourcedRecord):
    employee_code: str
    employee_id: str | None = None
    punch_time: datetime
    attendance_date: date | None = None   # business date; assigned by shift policy, not by the contract
    direction: PunchDirection = PunchDirection.UNKNOWN
    device_or_location: str | None = None

    _aware = field_validator("punch_time")(require_aware)
