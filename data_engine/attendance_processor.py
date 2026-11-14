"""Deterministic daily attendance classification (PRD 8). No AI involved.

PROVISIONAL LOGIC: the precedence below is a configurable mechanism, not an HR
policy. Every step that depends on an unapproved rule yields UNRESOLVED with a
reason, and every fact is PROVISIONAL until rules and source authority are approved.

Precedence for an eligible employee on a date:
  1. an approved exception adjustment
  2. approved leave (full day -> APPROVED_LEAVE, half day -> HALF_DAY)
  3. holiday / weekly off (unless a source reports work)
  4. source statuses (agreeing sources; conflicts use the approved authority, else UNRESOLVED)
  5. pending leave -> PENDING_APPROVAL
  6. incomplete punches -> MISSING_PUNCH
  7. no record -> rules.no_record_status, else UNRESOLVED
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from contracts.attendance import AttendanceStatus as S
from core.config import AttendanceRules, SourceAuthority
from database.models.attendance import AttendanceAdjustment, AttendancePunch, LeaveRecordRow, SourceAttendance
from database.models.hr import DimEmployee, EmployeeOrgHistory, HolidayCalendar
from database.models.staging import UploadRegistry
from data_engine.employee_mapper import verified_lookup

WORK_STATUSES = {S.PRESENT.value, S.WORK_FROM_HOME.value, S.HALF_DAY.value}
WEEKDAYS = ["MONDAY", "TUESDAY", "WEDNESDAY", "THURSDAY", "FRIDAY", "SATURDAY", "SUNDAY"]
SOURCE_SYSTEM_TO_KEY = {"BIZOM": "bizom", "POCKET_HRMS": "hrms"}


@dataclass
class SourceView:
    present: bool = False
    status: str | None = None          # mapped status (None = unmapped or absent)
    raw: str | None = None
    first_in: datetime | None = None
    last_out: datetime | None = None
    count: int = 0


@dataclass
class DayInputs:
    bizom: SourceView = field(default_factory=SourceView)
    hrms: SourceView = field(default_factory=SourceView)
    leave_approval: str | None = None
    leave_portion: str | None = None
    punches: list[tuple[datetime, str]] = field(default_factory=list)
    holiday: str | None = None
    weekly_off: bool = False
    adjustment: tuple[int, str] | None = None     # (exception_id, status)


@dataclass
class Classification:
    status: str
    reason: str


def classify(d: DayInputs, rules: AttendanceRules, authority: SourceAuthority) -> Classification:
    if d.adjustment:
        return Classification(d.adjustment[1], f"Adjusted by resolved exception #{d.adjustment[0]}")

    if d.leave_approval == "APPROVED":
        if d.leave_portion in ("FIRST_HALF", "SECOND_HALF"):
            return Classification(S.HALF_DAY, "Approved half-day leave")
        return Classification(S.APPROVED_LEAVE, "Approved leave")

    reported = {v.status for v in (d.bizom, d.hrms) if v.status}
    if d.holiday or d.weekly_off:
        worked = reported & WORK_STATUSES
        if len(worked) == 1:
            return Classification(worked.pop(), "Work reported on a non-working day")
        return Classification(S.HOLIDAY if d.holiday else S.WEEKLY_OFF, d.holiday or "Weekly off")

    if len(reported) == 1:
        return Classification(next(iter(reported)), "Reported by source" + ("s (agree)" if d.bizom.status and d.hrms.status else ""))
    if len(reported) > 1:
        office = authority.domains.get("OFFICE_ATTENDANCE")
        chosen = office.authoritative_source if (office and authority.approval_status == "APPROVED") else None
        view = {"BIZOM": d.bizom, "POCKET_HRMS": d.hrms}.get(chosen or "")
        if view and view.status:
            return Classification(view.status, f"Source conflict resolved by approved authority ({chosen})")
        return Classification(S.UNRESOLVED, "Sources disagree and no source authority is approved")
    if d.bizom.present or d.hrms.present:
        return Classification(S.UNRESOLVED, "Source status has no approved mapping")

    if d.leave_approval == "PENDING":
        return Classification(S.PENDING_APPROVAL, "Leave pending approval")

    if d.punches:
        directions = [p[1] for p in d.punches]
        if len(d.punches) % 2 == 1 or ("IN" in directions) != ("OUT" in directions):
            return Classification(S.MISSING_PUNCH, "Incomplete punch sequence")
        return Classification(S.UNRESOLVED, "Punches present without a status; punch policy not approved")

    if rules.calculation.no_record_status is not None:
        return Classification(rules.calculation.no_record_status, "No record (approved rule)")
    return Classification(S.UNRESOLVED, "No record; 'no record' rule not approved")


def is_eligible(emp: DimEmployee, day: date) -> bool:
    """Objective employment window only. Treatment of joiners/leavers beyond this is an HR rule."""
    if emp.joining_date and emp.joining_date > day:
        return False
    return not (emp.exit_date and emp.exit_date < day)


@dataclass
class EngineInputs:
    day: date
    employees: list[DimEmployee]
    org: dict[int, tuple[str | None, str | None]]
    inputs: dict[int, DayInputs]
    unmapped: list[dict]                       # source records without a verified mapping
    duplicates: list[dict]                     # repeated source records for one employee/date
    datasets_present: set[str]


def org_on(session: Session, day: date) -> dict[int, tuple[str | None, str | None]]:
    """Department/location effective on `day` (historical, PRD 7.4)."""
    rows = session.scalars(select(EmployeeOrgHistory).where(EmployeeOrgHistory.effective_from <= day)
                           .order_by(EmployeeOrgHistory.employee_key, EmployeeOrgHistory.effective_from))
    result: dict[int, tuple[str | None, str | None]] = {}
    for r in rows:
        if r.effective_to is None or r.effective_to >= day:
            result[r.employee_key] = (r.department_code, r.location_code)
    return result


def gather(session: Session, day: date, upload_ids: dict[str, list[int]], rules: AttendanceRules) -> EngineInputs:
    employees = list(session.scalars(select(DimEmployee)))
    org = org_on(session, day)
    for e in employees:   # fall back to the current snapshot when no history covers the date
        org.setdefault(e.employee_key, (e.department_code, e.location_code))
    lookup = verified_lookup(session)
    inputs: dict[int, DayInputs] = defaultdict(DayInputs)
    unmapped: dict[tuple[str, str], dict] = {}
    seen: dict[tuple[str, int], int] = defaultdict(int)
    duplicates: list[dict] = []

    att_ids = upload_ids.get("BIZOM_ATTENDANCE", []) + upload_ids.get("HRMS_ATTENDANCE", [])
    if att_ids:
        for r in session.scalars(select(SourceAttendance).where(SourceAttendance.upload_id.in_(att_ids),
                                                                 SourceAttendance.attendance_date == day)):
            key = lookup.get((r.source_system, r.source_employee_id))
            if key is None:
                unmapped[(r.source_system, r.source_employee_id)] = {
                    "source_system": r.source_system, "source_employee_id": r.source_employee_id,
                    "source_employee_name": r.source_employee_name, "status": r.source_status}
                continue
            seen[(r.source_system, key)] += 1
            if seen[(r.source_system, key)] == 2:
                duplicates.append({"employee_key": key, "source_system": r.source_system,
                                   "source_employee_id": r.source_employee_id})
            view = getattr(inputs[key], SOURCE_SYSTEM_TO_KEY[r.source_system])
            view.present, view.count = True, view.count + 1
            view.status, view.raw = r.mapped_status, r.source_status
            view.first_in, view.last_out = r.first_in, r.last_out

    leave_ids = upload_ids.get("HRMS_LEAVE_ALL", [])
    if leave_ids:
        latest: dict[int, LeaveRecordRow] = {}
        for r in session.scalars(select(LeaveRecordRow).where(LeaveRecordRow.upload_id.in_(leave_ids),
                                                               LeaveRecordRow.leave_date == day)
                                 .order_by(LeaveRecordRow.upload_id, LeaveRecordRow.id)):
            key = lookup.get((r.source_system, r.source_employee_id))
            if key is not None:
                latest[key] = r          # the most recent upload wins (handles cancellations)
        for key, r in latest.items():
            if r.approval_status in ("APPROVED", "PENDING"):
                inputs[key].leave_approval, inputs[key].leave_portion = r.approval_status, r.day_portion

    punch_ids = upload_ids.get("HRMS_PUNCH", [])
    if punch_ids:
        for r in session.scalars(select(AttendancePunch).where(AttendancePunch.upload_id.in_(punch_ids),
                                                                AttendancePunch.attendance_date == day)
                                 .order_by(AttendancePunch.punch_time)):
            key = lookup.get((r.source_system, r.source_employee_id))
            if key is not None:
                inputs[key].punches.append((r.punch_time, r.direction))

    holidays = {h.location_code: h.holiday_name for h in session.scalars(
        select(HolidayCalendar).where(HolidayCalendar.holiday_date == day))}
    weekly = rules.calculation.weekly_off_days or ()
    for e in employees:
        loc = org[e.employee_key][1]
        di = inputs[e.employee_key]
        di.holiday = holidays.get(loc) or holidays.get(None)
        di.weekly_off = WEEKDAYS[day.weekday()] in weekly

    for adj in session.scalars(select(AttendanceAdjustment).where(AttendanceAdjustment.attendance_date == day,
                                                                   AttendanceAdjustment.is_active.is_(True))
                               .order_by(AttendanceAdjustment.id)):
        inputs[adj.employee_key].adjustment = (adj.exception_id, adj.adjusted_status)

    present = {ds for ds, ids in upload_ids.items() if ids}
    return EngineInputs(day, employees, org, dict(inputs), list(unmapped.values()), duplicates, present)


def build_facts(engine_inputs: EngineInputs, rules: AttendanceRules, authority: SourceAuthority, official: bool) -> list[dict]:
    facts = []
    for emp in engine_inputs.employees:
        if not is_eligible(emp, engine_inputs.day):
            continue
        d = engine_inputs.inputs.get(emp.employee_key, DayInputs())
        c = classify(d, rules, authority)
        punch_times = [p[0] for p in d.punches]
        source_ins = [t for t in (d.hrms.first_in, d.bizom.first_in) if t]
        source_outs = [t for t in (d.hrms.last_out, d.bizom.last_out) if t]
        first_in = min(source_ins + punch_times[:1], default=None)
        last_out = max(source_outs + (punch_times[-1:] if len(punch_times) > 1 else []), default=None)
        dept, loc = engine_inputs.org.get(emp.employee_key, (None, None))
        facts.append({
            "employee_key": emp.employee_key, "attendance_date": engine_inputs.day,
            "department_code": dept, "location_code": loc, "final_status": str(c.status),
            "bizom_status": d.bizom.status or (f"UNMAPPED:{d.bizom.raw}"[:30] if d.bizom.present else None),
            "hrms_status": d.hrms.status or (f"UNMAPPED:{d.hrms.raw}"[:30] if d.hrms.present else None),
            "leave_status": d.leave_approval, "first_in": first_in, "last_out": last_out,
            "punch_count": len(d.punches), "record_status": "OFFICIAL" if official else "PROVISIONAL",
            "rule_version": rules.rule_version, "reason": c.reason[:300],
        })
    return facts


def current_upload_ids(session: Session, day: date) -> dict[str, list[int]]:
    """Inputs for `day`: current daily uploads for the date, plus every current leave upload
    (leave files may cover future dates)."""
    out: dict[str, list[int]] = defaultdict(list)
    for u in session.scalars(select(UploadRegistry).where(UploadRegistry.is_current.is_(True),
                                                          UploadRegistry.status == "READY_FOR_PROCESSING")):
        if u.dataset_id == "HRMS_LEAVE":
            out["HRMS_LEAVE_ALL"].append(u.upload_id)
            if u.reporting_date == day:
                out["HRMS_LEAVE"].append(u.upload_id)
        elif u.reporting_date == day:
            out[u.dataset_id].append(u.upload_id)
        elif u.dataset_id in ("HRMS_EMPLOYEE_MASTER", "DEPARTMENT_MASTER", "REPORTING_HIERARCHY", "HOLIDAY_CALENDAR") \
                and u.reporting_date <= day:
            out[u.dataset_id].append(u.upload_id)
    return dict(out)
