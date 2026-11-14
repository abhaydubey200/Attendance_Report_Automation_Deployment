"""Employee contract (PRD 6.2 / 7.1). Provisional field set."""

from __future__ import annotations

from datetime import date

from pydantic import model_validator

from contracts.base import SourcedRecord


class EmployeeRecord(SourcedRecord):
    employee_id: str | None = None          # internal id, assigned by mapping (Phase 4)
    employee_code: str
    employee_name: str | None = None
    department_id: str | None = None
    location_id: str | None = None
    designation: str | None = None
    employment_type: str | None = None
    employment_status: str | None = None
    joining_date: date | None = None
    exit_date: date | None = None
    reporting_manager_code: str | None = None
    effective_from: date | None = None
    effective_to: date | None = None

    @model_validator(mode="after")
    def _date_order(self) -> "EmployeeRecord":
        if self.joining_date and self.exit_date and self.exit_date < self.joining_date:
            raise ValueError("exit_date precedes joining_date")
        if self.effective_from and self.effective_to and self.effective_to < self.effective_from:
            raise ValueError("effective_to precedes effective_from")
        return self
