"""Column definitions for each dataset, built by an administrator from an inspected
sample file (PRD 6.1). Nothing here assumes Bizom or Pocket HRMS column names: the
administrator maps the file's own columns onto the fixed internal fields below."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from contracts.attendance import AttendanceStatus
from contracts.leave import LeaveApprovalStatus, LeaveDayPortion
from contracts.punch import PunchDirection

FieldType = Literal["str", "date", "datetime", "time"]

# Internal fields each dataset can map to: name -> (type, required).
TARGET_FIELDS: dict[str, dict[str, tuple[FieldType, bool]]] = {
    "ATTENDANCE": {
        "source_employee_id": ("str", True),
        "source_employee_name": ("str", False),
        "attendance_date": ("date", True),
        "source_status": ("str", False),
        "first_in": ("datetime", False),
        "last_out": ("datetime", False),
        "first_in_time": ("time", False),
        "last_out_time": ("time", False),
        "source_record_id": ("str", False),
    },
    "LEAVE": {
        "source_employee_id": ("str", True),
        "leave_date": ("date", False),
        "from_date": ("date", False),
        "to_date": ("date", False),
        "leave_type": ("str", False),
        "approval_status": ("str", True),
        "day_portion": ("str", False),
        "source_record_id": ("str", False),
    },
    "PUNCH": {
        "source_employee_id": ("str", True),
        "punch_time": ("datetime", False),
        "punch_date": ("date", False),
        "punch_clock": ("time", False),
        "direction": ("str", False),
        "device_or_location": ("str", False),
        "source_record_id": ("str", False),
    },
    "EMPLOYEE": {
        "employee_code": ("str", True),
        "employee_name": ("str", False),
        "department_code": ("str", False),
        "location_code": ("str", False),
        "designation": ("str", False),
        "employment_type": ("str", False),
        "employment_status": ("str", False),
        "joining_date": ("date", False),
        "exit_date": ("date", False),
        "reporting_manager_code": ("str", False),
    },
    "DEPARTMENT": {
        "department_code": ("str", True),
        "department_name": ("str", True),
        "parent_department_code": ("str", False),
        "hod_employee_code": ("str", False),
        "is_active": ("str", False),
    },
    "HIERARCHY": {
        "employee_code": ("str", True),
        "manager_code": ("str", False),
    },
    "HOLIDAY": {
        "holiday_date": ("date", True),
        "holiday_name": ("str", True),
        "location_code": ("str", False),
    },
}

DATASET_KIND: dict[str, str] = {
    "BIZOM_ATTENDANCE": "ATTENDANCE",
    "HRMS_ATTENDANCE": "ATTENDANCE",
    "HRMS_LEAVE": "LEAVE",
    "HRMS_PUNCH": "PUNCH",
    "HRMS_EMPLOYEE_MASTER": "EMPLOYEE",
    "DEPARTMENT_MASTER": "DEPARTMENT",
    "REPORTING_HIERARCHY": "HIERARCHY",
    "HOLIDAY_CALENDAR": "HOLIDAY",
}

# Value maps translate a source's own codes into internal vocabularies.
VALUE_MAP_TARGETS: dict[str, set[str]] = {
    "source_status": {s.value for s in AttendanceStatus},
    "approval_status": {s.value for s in LeaveApprovalStatus},
    "day_portion": {s.value for s in LeaveDayPortion},
    "direction": {s.value for s in PunchDirection},
    "is_active": {"TRUE", "FALSE"},
}

# Field whose value must equal the upload's reporting date for daily datasets.
PERIOD_FIELD: dict[str, str] = {"ATTENDANCE": "attendance_date", "PUNCH": "punch_date"}


class SchemaDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    columns: dict[str, str] = Field(description="source column -> internal field")
    primary_key: list[str] = Field(default_factory=list, description="internal fields forming the business key")
    date_formats: list[str] = Field(default_factory=lambda: ["%Y-%m-%d"])
    datetime_formats: list[str] = Field(default_factory=lambda: ["%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"])
    time_formats: list[str] = Field(default_factory=lambda: ["%H:%M:%S", "%H:%M"])
    value_maps: dict[str, dict[str, str]] = Field(default_factory=dict)
    check_reporting_period: bool = True

    def validate_for(self, dataset_id: str) -> list[str]:
        """Problems that make this definition unusable for `dataset_id` (empty = OK)."""
        kind = DATASET_KIND.get(dataset_id)
        if kind is None:
            return [f"Unknown dataset {dataset_id}."]
        fields = TARGET_FIELDS[kind]
        problems = []
        targets = list(self.columns.values())
        unknown = sorted(set(targets) - set(fields))
        if unknown:
            problems.append(f"Unknown internal fields: {', '.join(unknown)}.")
        dupes = sorted({t for t in targets if targets.count(t) > 1})
        if dupes:
            problems.append(f"Fields mapped more than once: {', '.join(dupes)}.")
        for name, (_, required) in fields.items():
            if required and name not in targets:
                problems.append(f"Required field '{name}' is not mapped.")
        if kind == "LEAVE" and "leave_date" not in targets and not {"from_date", "to_date"} <= set(targets):
            problems.append("Map either 'leave_date' or both 'from_date' and 'to_date'.")
        if kind == "PUNCH" and "punch_time" not in targets and not {"punch_date", "punch_clock"} <= set(targets):
            problems.append("Map either 'punch_time' or both 'punch_date' and 'punch_clock'.")
        missing_pk = sorted(set(self.primary_key) - set(targets))
        if missing_pk:
            problems.append(f"Business-key fields not mapped: {', '.join(missing_pk)}.")
        for field_name, mapping in self.value_maps.items():
            allowed = VALUE_MAP_TARGETS.get(field_name)
            if allowed is None:
                problems.append(f"No value map is supported for '{field_name}'.")
                continue
            bad = sorted({v for v in mapping.values() if v not in allowed})
            if bad:
                problems.append(f"Value map for '{field_name}' uses unknown values: {', '.join(bad)}.")
        return problems

    @property
    def target_to_source(self) -> dict[str, str]:
        return {target: source for source, target in self.columns.items()}

    @model_validator(mode="after")
    def _non_empty(self) -> "SchemaDefinition":
        if not self.columns:
            raise ValueError("at least one column must be mapped")
        return self
