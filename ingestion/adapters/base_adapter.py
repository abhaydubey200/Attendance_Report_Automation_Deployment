"""Source adapters: typed rows -> standardized contracts (PRD 6.3).

Manual-upload adapters and future automated connectors must emit the same contracts;
the engine never knows how a record arrived.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta

from pydantic import ValidationError

from contracts.attendance import AttendanceRecord, AttendanceStatus
from contracts.base import SourceSystem
from contracts.department import DepartmentRecord
from contracts.employee import EmployeeRecord
from contracts.leave import LeaveApprovalStatus, LeaveDayPortion, LeaveRecord
from contracts.punch import PunchDirection, PunchEvent
from ingestion.schema_definition import DATASET_KIND
from ingestion.validator import TypedRow


@dataclass
class AdapterOutput:
    records: list = field(default_factory=list)
    rejected: list[tuple[int, str]] = field(default_factory=list)   # (row_number, reason)


@dataclass(frozen=True)
class HierarchyLine:
    employee_code: str
    manager_code: str | None


@dataclass(frozen=True)
class HolidayEntry:
    holiday_date: object
    holiday_name: str
    location_code: str | None


@dataclass(frozen=True)
class SummaryLine:
    """One Pocket HRMS AttendanceSummary record: who, which category, the day's status label and punches."""
    employee_code: str
    employee_name: str | None
    category: str | None
    attendance: AttendanceRecord
    punches: tuple[PunchEvent, ...]


class BaseAdapter:
    kind: str = ""

    def __init__(self, source_system: SourceSystem, upload_id: int | None) -> None:
        self.source_system = source_system
        self.upload_id = upload_id

    def _base(self, row: TypedRow) -> dict:
        v = row.values
        return {"source_system": self.source_system, "upload_id": self.upload_id,
                "source_record_id": v.get("source_record_id") or f"row-{row.row_number}"}

    def convert(self, row: TypedRow) -> list:
        raise NotImplementedError

    def run(self, rows: list[TypedRow]) -> AdapterOutput:
        out = AdapterOutput()
        for row in rows:
            try:
                out.records.extend(self.convert(row))
            except (ValidationError, ValueError) as exc:
                out.rejected.append((row.row_number, str(exc).splitlines()[0][:200]))
        return out


class AttendanceAdapter(BaseAdapter):
    kind = "ATTENDANCE"

    def convert(self, row: TypedRow) -> list:
        v = row.values
        status = v.get("source_status_mapped")
        return [AttendanceRecord(
            **self._base(row),
            employee_code=v["source_employee_id"],
            attendance_date=v["attendance_date"],
            source_status=v.get("source_status"),
            attendance_status=AttendanceStatus(status) if status else None,
            first_in_time=v.get("first_in"),
            last_out_time=v.get("last_out"),
        )]


class AttendanceSummaryAdapter(BaseAdapter):
    kind = "ATTENDANCE_SUMMARY"

    def convert(self, row: TypedRow) -> list:
        v = row.values
        status = v.get("source_status_mapped")
        base = self._base(row)
        code = v["source_employee_id"]
        record = AttendanceRecord(
            **base, employee_code=code, attendance_date=v["attendance_date"], source_status=v.get("source_status"),
            attendance_status=AttendanceStatus(status) if status else None,
            first_in_time=v.get("first_in"), last_out_time=v.get("last_out"),
        )
        punches = []
        for direction, field_name in ((PunchDirection.IN, "first_in"), (PunchDirection.OUT, "last_out")):
            if v.get(field_name):
                punches.append(PunchEvent(**{**base, "source_record_id": f"{base['source_record_id']}:{direction.value}"},
                                          employee_code=code, punch_time=v[field_name], attendance_date=v["attendance_date"],
                                          direction=direction))
        return [SummaryLine(code, v.get("source_employee_name"), v.get("category"), record, tuple(punches))]


class LeaveAdapter(BaseAdapter):
    kind = "LEAVE"

    def convert(self, row: TypedRow) -> list:
        v = row.values
        approval = v.get("approval_status_mapped") or LeaveApprovalStatus.UNKNOWN.value
        portion = v.get("day_portion_mapped") or (LeaveDayPortion.FULL_DAY.value if not v.get("day_portion") else LeaveDayPortion.UNKNOWN.value)
        if v.get("leave_date"):
            days = [v["leave_date"]]
        else:
            start, end = v["from_date"], v["to_date"]
            days = [start + timedelta(days=i) for i in range((end - start).days + 1)]
        base = self._base(row)
        return [LeaveRecord(
            **{**base, "source_record_id": f"{base['source_record_id']}#{i}" if len(days) > 1 else base["source_record_id"]},
            employee_code=v["source_employee_id"], leave_date=d, leave_type=v.get("leave_type"),
            source_approval_status=v.get("approval_status"),
            approval_status=LeaveApprovalStatus(approval), day_portion=LeaveDayPortion(portion),
        ) for i, d in enumerate(days)]


class PunchAdapter(BaseAdapter):
    kind = "PUNCH"

    def convert(self, row: TypedRow) -> list:
        v = row.values
        direction = v.get("direction_mapped") or PunchDirection.UNKNOWN.value
        return [PunchEvent(
            **self._base(row), employee_code=v["source_employee_id"], punch_time=v["punch_time"],
            attendance_date=v.get("punch_date") or v["punch_time"].date(),
            direction=PunchDirection(direction), device_or_location=v.get("device_or_location"),
        )]


class EmployeeMasterAdapter(BaseAdapter):
    kind = "EMPLOYEE"

    def convert(self, row: TypedRow) -> list:
        v = row.values
        return [EmployeeRecord(
            **self._base(row), employee_code=v["employee_code"], employee_name=v.get("employee_name"),
            department_id=v.get("department_code"), location_id=v.get("location_code"), designation=v.get("designation"),
            employment_type=v.get("employment_type"), employment_status=v.get("employment_status"),
            joining_date=v.get("joining_date"), exit_date=v.get("exit_date"),
            reporting_manager_code=v.get("reporting_manager_code"),
        )]


class DepartmentAdapter(BaseAdapter):
    kind = "DEPARTMENT"

    def convert(self, row: TypedRow) -> list:
        v = row.values
        active = v.get("is_active_mapped")
        return [DepartmentRecord(
            **self._base(row), department_code=v["department_code"].strip().upper(), department_name=v["department_name"],
            parent_department_code=(v.get("parent_department_code") or "").strip().upper() or None,
            hod_employee_code=v.get("hod_employee_code"), is_active=active != "FALSE",
        )]


class HierarchyAdapter(BaseAdapter):
    kind = "HIERARCHY"

    def convert(self, row: TypedRow) -> list:
        v = row.values
        return [HierarchyLine(v["employee_code"], v.get("manager_code"))]


class HolidayAdapter(BaseAdapter):
    kind = "HOLIDAY"

    def convert(self, row: TypedRow) -> list:
        v = row.values
        return [HolidayEntry(v["holiday_date"], v["holiday_name"], (v.get("location_code") or "").strip().upper() or None)]


ADAPTERS: dict[str, type[BaseAdapter]] = {
    a.kind: a for a in (AttendanceAdapter, AttendanceSummaryAdapter, LeaveAdapter, PunchAdapter, EmployeeMasterAdapter,
                        DepartmentAdapter, HierarchyAdapter, HolidayAdapter)
}


def adapter_for(dataset_id: str, source_system: SourceSystem, upload_id: int | None) -> BaseAdapter:
    return ADAPTERS[DATASET_KIND[dataset_id]](source_system, upload_id)
