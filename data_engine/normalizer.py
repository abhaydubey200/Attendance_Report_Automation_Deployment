"""Persist standardized records (RAW -> STANDARDIZED layer, PRD 5.8).

Masters (employee, department, hierarchy, holidays) update the hr.* dimensions with
effective dating; daily datasets land in attendance.* source tables linked to their
upload. Employee identities are resolved at processing time, so a mapping fixed later
applies to the next run without re-uploading.
"""

from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from contracts.attendance import AttendanceRecord
from contracts.department import DepartmentRecord
from contracts.employee import EmployeeRecord
from contracts.leave import LeaveRecord
from contracts.punch import PunchEvent
from database.models.attendance import AttendancePunch, LeaveRecordRow, SourceAttendance
from database.models.hr import DimDepartment, DimEmployee, EmployeeOrgHistory, HolidayCalendar, ReportingHierarchy
from data_engine.employee_mapper import ensure_mappings, refresh_exact_matches
from ingestion.adapters.base_adapter import HierarchyLine, HolidayEntry


def _norm(code: str | None) -> str | None:
    return code.strip().upper() if code and code.strip() else None


def _apply_org_history(session: Session, emp: DimEmployee, dept: str | None, loc: str | None, as_of: date, upload_id: int) -> None:
    open_row = session.scalar(select(EmployeeOrgHistory).where(
        EmployeeOrgHistory.employee_key == emp.employee_key, EmployeeOrgHistory.effective_to.is_(None)))
    if open_row and open_row.department_code == dept and open_row.location_code == loc:
        return
    if open_row:
        if open_row.effective_from >= as_of:
            # Same-day correction: replace the assignment for that start date.
            open_row.department_code, open_row.location_code, open_row.source_upload_id = dept, loc, upload_id
            return
        open_row.effective_to = as_of - timedelta(days=1)
        start = as_of
    else:
        # First snapshot: assumed to apply from joining (no earlier history exists).
        start = min(as_of, emp.joining_date) if emp.joining_date else as_of
    session.add(EmployeeOrgHistory(employee_key=emp.employee_key, department_code=dept, location_code=loc,
                                   effective_from=start, source_upload_id=upload_id))


def save_employee_master(session: Session, records: list[EmployeeRecord], as_of: date, upload_id: int) -> dict:
    existing = {e.employee_code: e for e in session.scalars(select(DimEmployee))}
    created = updated = 0
    for r in records:
        emp = existing.get(r.employee_code)
        if emp is None:
            emp = DimEmployee(employee_code=r.employee_code)
            session.add(emp)
            existing[r.employee_code] = emp
            created += 1
        else:
            updated += 1
        emp.employee_name, emp.designation = r.employee_name, r.designation
        emp.employment_type, emp.employment_status = r.employment_type, r.employment_status
        emp.joining_date, emp.exit_date = r.joining_date, r.exit_date
        emp.department_code, emp.location_code = _norm(r.department_id), _norm(r.location_id)
        emp.reporting_manager_code, emp.source_upload_id = r.reporting_manager_code, upload_id
        session.flush()
        _apply_org_history(session, emp, emp.department_code, emp.location_code, as_of, upload_id)
    session.flush()
    verified = refresh_exact_matches(session)
    return {"created": created, "updated": updated, "mappings_verified": verified}


def save_departments(session: Session, records: list[DepartmentRecord], upload_id: int) -> dict:
    count = 0
    for r in records:
        dept = session.get(DimDepartment, r.department_code) or DimDepartment(department_code=r.department_code)
        dept.department_name, dept.parent_department_code = r.department_name, r.parent_department_code
        dept.hod_employee_code, dept.is_active, dept.source_upload_id = r.hod_employee_code, r.is_active, upload_id
        session.add(dept)
        count += 1
    session.flush()
    return {"departments": count}


def save_hierarchy(session: Session, lines: list[HierarchyLine], as_of: date, upload_id: int) -> dict:
    changed = 0
    for line in lines:
        open_row = session.scalar(select(ReportingHierarchy).where(
            ReportingHierarchy.employee_code == line.employee_code, ReportingHierarchy.effective_to.is_(None)))
        if open_row and open_row.manager_code == line.manager_code:
            continue
        if open_row:
            if open_row.effective_from >= as_of:
                open_row.manager_code = line.manager_code
                changed += 1
                continue
            open_row.effective_to = as_of - timedelta(days=1)
        session.add(ReportingHierarchy(employee_code=line.employee_code, manager_code=line.manager_code,
                                       effective_from=as_of, source_upload_id=upload_id))
        changed += 1
    session.flush()
    return {"hierarchy_changes": changed}


def save_holidays(session: Session, entries: list[HolidayEntry], upload_id: int) -> dict:
    count = 0
    for h in entries:
        row = session.scalar(select(HolidayCalendar).where(HolidayCalendar.holiday_date == h.holiday_date,
                                                          HolidayCalendar.location_code.is_(None) if h.location_code is None
                                                          else HolidayCalendar.location_code == h.location_code))
        if row is None:
            row = HolidayCalendar(holiday_date=h.holiday_date, location_code=h.location_code)
            session.add(row)
        row.holiday_name, row.source_upload_id = h.holiday_name, upload_id
        count += 1
    session.flush()
    return {"holidays": count}


def save_attendance(session: Session, records: list[AttendanceRecord], names: dict[str, str | None], upload_id: int) -> dict:
    for r in records:
        session.add(SourceAttendance(
            upload_id=upload_id, source_system=r.source_system.value, source_record_id=r.source_record_id,
            source_employee_id=r.employee_code, source_employee_name=names.get(r.employee_code),
            attendance_date=r.attendance_date, source_status=r.source_status,
            mapped_status=r.attendance_status.value if r.attendance_status else None,
            first_in=r.first_in_time, last_out=r.last_out_time))
    session.flush()
    system = records[0].source_system.value if records else None
    mapping = ensure_mappings(session, system, names) if system else {}
    return {"records": len(records), "mappings": mapping}


def save_leave(session: Session, records: list[LeaveRecord], upload_id: int) -> dict:
    for r in records:
        session.add(LeaveRecordRow(
            upload_id=upload_id, source_system=r.source_system.value, source_record_id=r.source_record_id,
            source_employee_id=r.employee_code, leave_date=r.leave_date, leave_type=r.leave_type,
            source_approval_status=r.source_approval_status, approval_status=r.approval_status.value,
            day_portion=r.day_portion.value))
    session.flush()
    system = records[0].source_system.value if records else None
    mapping = ensure_mappings(session, system, {r.employee_code: None for r in records}) if system else {}
    return {"records": len(records), "mappings": mapping}


def save_punches(session: Session, records: list[PunchEvent], upload_id: int) -> dict:
    for r in records:
        session.add(AttendancePunch(
            upload_id=upload_id, source_system=r.source_system.value, source_record_id=r.source_record_id,
            source_employee_id=r.employee_code, punch_time=r.punch_time, attendance_date=r.attendance_date,
            direction=r.direction.value, device_or_location=r.device_or_location))
    session.flush()
    system = records[0].source_system.value if records else None
    mapping = ensure_mappings(session, system, {r.employee_code: None for r in records}) if system else {}
    return {"records": len(records), "mappings": mapping}
