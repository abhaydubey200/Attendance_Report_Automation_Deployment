"""Department and reporting-hierarchy contracts (PRD 7.4)."""

from __future__ import annotations

from datetime import date

from pydantic import model_validator

from contracts.base import SourcedRecord


class DepartmentRecord(SourcedRecord):
    department_code: str
    department_name: str
    parent_department_code: str | None = None
    hod_employee_code: str | None = None
    is_active: bool = True


class EmployeeOrgAssignment(SourcedRecord):
    """Effective-dated department assignment, so history is never overwritten."""

    employee_code: str
    department_code: str
    location_code: str | None = None
    effective_from: date
    effective_to: date | None = None

    @model_validator(mode="after")
    def _date_order(self) -> "EmployeeOrgAssignment":
        if self.effective_to and self.effective_to < self.effective_from:
            raise ValueError("effective_to precedes effective_from")
        return self

    def applies_on(self, day: date) -> bool:
        return self.effective_from <= day and (self.effective_to is None or day <= self.effective_to)
