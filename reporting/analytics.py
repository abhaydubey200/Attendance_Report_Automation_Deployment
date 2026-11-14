"""Read-only analytics over the CURRENT run of each date (PRD 12). Every query is
scoped to the caller's departments; employee-level rows need ATTENDANCE_VIEW_EMPLOYEE."""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from datetime import date, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from core.config import AttendanceRules
from core.exceptions import AuthorizationError
from core.timeutils import to_ist
from database.models.attendance import AttendanceException, AttendanceReconciliation, FactAttendanceDaily, ProcessingRun
from database.models.hr import DimDepartment, DimEmployee, EmployeeSourceMapping
from database.models.staging import UploadRegistry, ValidationIssue
from data_engine import kpi_calculator
from security.authorization import can_view_employee_records, has_all_departments, has_permission
from security.permissions import Perm, Principal

MAX_RANGE_DAYS = 92
ROW_LIMIT = 2000


def dept_scope(principal: Principal) -> set[str] | None:
    return None if has_all_departments(principal) else set(principal.departments)


def _scoped(q, principal: Principal):
    scope = dept_scope(principal)
    return q if scope is None else q.where(FactAttendanceDaily.department_code.in_(scope or {"__none__"}))


def _check_range(start: date, end: date) -> None:
    if end < start:
        raise ValueError("End date is before start date.")
    if (end - start).days > MAX_RANGE_DAYS:
        raise ValueError(f"Choose a range of at most {MAX_RANGE_DAYS} days.")


def current_run(session: Session, day: date | None) -> ProcessingRun | None:
    q = select(ProcessingRun).where(ProcessingRun.is_current.is_(True))
    q = q.where(ProcessingRun.reporting_date == day) if day else q.order_by(ProcessingRun.reporting_date.desc())
    return session.scalar(q)


def run_info(run: ProcessingRun | None) -> dict | None:
    if run is None:
        return None
    return {"run_id": run.run_id, "run_ref": run.run_ref, "reporting_date": run.reporting_date.isoformat(),
            "state": run.state, "rule_version": run.rule_version, "rules_approved": run.rules_approved,
            "finished_at": run.finished_at.isoformat() if run.finished_at else None, "ai_status": run.ai_status}


def _statuses(session: Session, principal: Principal, run_ids: list[int]):
    q = select(FactAttendanceDaily.run_id, FactAttendanceDaily.attendance_date, FactAttendanceDaily.department_code,
               FactAttendanceDaily.location_code, FactAttendanceDaily.final_status).where(FactAttendanceDaily.run_id.in_(run_ids))
    return session.execute(_scoped(q, principal)).all()


def summary(session: Session, principal: Principal, rules: AttendanceRules, day: date | None = None) -> dict:
    run = current_run(session, day)
    if run is None:
        return {"run": None}
    rows = _statuses(session, principal, [run.run_id])
    active = session.scalar(select(func.count()).select_from(DimEmployee).where(
        (DimEmployee.exit_date.is_(None)) | (DimEmployee.exit_date >= run.reporting_date))) if dept_scope(principal) is None else None
    kpis = kpi_calculator.summarize([r.final_status for r in rows], rules, active)
    names = {d.department_code: d.department_name for d in session.scalars(select(DimDepartment))}
    by_dept, by_loc = defaultdict(list), defaultdict(list)
    for r in rows:
        by_dept[r.department_code or "UNASSIGNED"].append(r.final_status)
        by_loc[r.location_code or "UNASSIGNED"].append(r.final_status)
    scope = dept_scope(principal)
    exc_q = select(AttendanceException.status, AttendanceException.category, AttendanceException.severity).where(
        AttendanceException.run_id == run.run_id)
    if scope is not None:
        exc_q = exc_q.where(AttendanceException.department_code.in_(scope or {"__none__"}))
    exceptions = session.execute(exc_q).all()
    uploads = list(session.scalars(select(UploadRegistry).where(UploadRegistry.reporting_date == run.reporting_date,
                                                                UploadRegistry.is_current.is_(True))))
    stats = json.loads(run.stats or "{}")
    return {
        "run": run_info(run),
        "kpis": kpis,
        "departments": [{"department_code": k, "department_name": names.get(k, k),
                         **_group(v, rules)} for k, v in sorted(by_dept.items())],
        "locations": [{"location_code": k, **_group(v, rules)} for k, v in sorted(by_loc.items())],
        "trend": trend(session, principal, rules, run.reporting_date - timedelta(days=13), run.reporting_date),
        "exceptions": {
            "open": sum(1 for e in exceptions if e.status in ("PENDING_REVIEW", "ASSIGNED", "UNDER_REVIEW")),
            "by_category": dict(Counter(e.category for e in exceptions)),
            "critical": sum(1 for e in exceptions if e.severity in ("HIGH", "CRITICAL")),
        },
        "data_quality": {
            "uploaded_datasets": len(uploads),
            "missing_datasets": stats.get("missing_datasets", []),
            "invalid_records": sum(u.invalid_rows for u in uploads),
            "unmapped_employees": session.scalar(select(func.count()).select_from(EmployeeSourceMapping)
                                                 .where(EmployeeSourceMapping.status == "PENDING")) if scope is None else None,
            "conflicting_records": stats.get("reconciliation", {}).get("counts", {}).get("STATUS_CONFLICT", 0) if scope is None else None,
        },
        "last_successful_run": run_info(session.scalar(select(ProcessingRun).where(
            ProcessingRun.state.in_(["READY_FOR_REVIEW", "APPROVED", "DISTRIBUTING", "COMPLETED"]))
            .order_by(ProcessingRun.finished_at.desc()))),
    }


def _group(statuses: list[str], rules: AttendanceRules) -> dict:
    s = kpi_calculator.summarize(statuses, rules)
    return {"eligible": s["eligible_employees"], "counts": s["counts"],
            "attendance_pct": s["attendance_pct"], "absenteeism_pct": s["absenteeism_pct"]}


def trend(session: Session, principal: Principal, rules: AttendanceRules, start: date, end: date,
          department: str | None = None) -> list[dict]:
    _check_range(start, end)
    runs = {r.run_id: r.reporting_date for r in session.scalars(select(ProcessingRun).where(
        ProcessingRun.is_current.is_(True), ProcessingRun.reporting_date.between(start, end)))}
    if not runs:
        return []
    by_day = defaultdict(list)
    for r in _statuses(session, principal, list(runs)):
        if department and r.department_code != department:
            continue
        by_day[r.attendance_date].append(r.final_status)
    return [{"date": d.isoformat(), **_group(v, rules)} for d, v in sorted(by_day.items())]


def employee_rows(session: Session, principal: Principal, day: date, statuses: set[str] | None = None,
                  department: str | None = None) -> list[dict]:
    if not has_permission(principal, Perm.ATTENDANCE_VIEW_EMPLOYEE):
        raise AuthorizationError("employee-level data not permitted")
    run = current_run(session, day)
    if run is None:
        return []
    q = (select(FactAttendanceDaily, DimEmployee).join(DimEmployee, DimEmployee.employee_key == FactAttendanceDaily.employee_key)
         .where(FactAttendanceDaily.run_id == run.run_id).order_by(DimEmployee.employee_code).limit(ROW_LIMIT))
    q = _scoped(q, principal)
    if statuses:
        q = q.where(FactAttendanceDaily.final_status.in_(statuses))
    if department:
        q = q.where(FactAttendanceDaily.department_code == department)
    return [_fact_row(f, e) for f, e in session.execute(q)]


def _fact_row(f: FactAttendanceDaily, e: DimEmployee) -> dict:
    return {"employee_code": e.employee_code, "employee_name": e.employee_name, "department_code": f.department_code,
            "location_code": f.location_code, "date": f.attendance_date.isoformat(), "status": f.final_status,
            "bizom_status": f.bizom_status, "hrms_status": f.hrms_status, "leave_status": f.leave_status,
            "first_in": to_ist(f.first_in).strftime("%H:%M") if f.first_in else None,
            "last_out": to_ist(f.last_out).strftime("%H:%M") if f.last_out else None,
            "punch_count": f.punch_count, "record_status": f.record_status, "reason": f.reason}


def employee_history(session: Session, principal: Principal, employee_code: str, start: date, end: date) -> dict:
    _check_range(start, end)
    emp = session.scalar(select(DimEmployee).where(DimEmployee.employee_code == employee_code.strip()))
    if emp is None:
        raise LookupError("employee not found")
    run_ids = [r.run_id for r in session.scalars(select(ProcessingRun).where(
        ProcessingRun.is_current.is_(True), ProcessingRun.reporting_date.between(start, end)))]
    rows = []
    if run_ids:
        for f in session.scalars(select(FactAttendanceDaily).where(FactAttendanceDaily.employee_key == emp.employee_key,
                                                                  FactAttendanceDaily.run_id.in_(run_ids))
                                 .order_by(FactAttendanceDaily.attendance_date)):
            if can_view_employee_records(principal, f.department_code or ""):
                rows.append(_fact_row(f, emp))
    if not rows and not can_view_employee_records(principal, emp.department_code or ""):
        raise LookupError("employee not found")      # do not reveal out-of-scope employees
    exceptions = [{"exception_id": x.exception_id, "date": x.attendance_date.isoformat(), "category": x.category,
                   "status": x.status} for x in session.scalars(select(AttendanceException).where(
                       AttendanceException.employee_key == emp.employee_key, AttendanceException.run_id.in_(run_ids or [-1])))]
    return {"employee_code": emp.employee_code, "employee_name": emp.employee_name, "rows": rows,
            "summary": dict(Counter(r["status"] for r in rows)), "exceptions": exceptions}


def data_quality(session: Session, start: date, end: date) -> dict:
    _check_range(start, end)
    uploads = list(session.scalars(select(UploadRegistry).where(UploadRegistry.reporting_date.between(start, end))
                                   .order_by(UploadRegistry.upload_id.desc())))
    ids = [u.upload_id for u in uploads]
    by_code = dict(session.execute(select(ValidationIssue.code, func.count()).where(ValidationIssue.upload_id.in_(ids or [-1]))
                                   .group_by(ValidationIssue.code)).all())
    runs = list(session.scalars(select(ProcessingRun).where(ProcessingRun.is_current.is_(True),
                                                            ProcessingRun.reporting_date.between(start, end))))
    missing = {r.reporting_date.isoformat(): json.loads(r.stats or "{}").get("missing_datasets", []) for r in runs}
    recon = Counter()
    for r in runs:
        recon.update(json.loads(r.stats or "{}").get("reconciliation", {}).get("counts", {}))
    return {
        "uploads": [{"upload_id": u.upload_id, "dataset_id": u.dataset_id, "reporting_date": u.reporting_date.isoformat(),
                     "file": u.original_filename, "validation_status": u.validation_status, "total": u.total_rows,
                     "valid": u.valid_rows, "invalid": u.invalid_rows, "duplicates": u.duplicate_rows,
                     "warnings": u.warning_count, "is_current": u.is_current} for u in uploads],
        "totals": {"source_records": sum(u.total_rows for u in uploads), "valid": sum(u.valid_rows for u in uploads),
                   "invalid": sum(u.invalid_rows for u in uploads), "duplicates": sum(u.duplicate_rows for u in uploads),
                   "rejected_uploads": sum(1 for u in uploads if u.validation_status == "REJECTED")},
        "issues_by_code": by_code,
        "unmapped_employees": session.scalar(select(func.count()).select_from(EmployeeSourceMapping)
                                             .where(EmployeeSourceMapping.status == "PENDING")),
        "missing_datasets": missing,
        "reconciliation": dict(recon),
        "unresolved_exceptions": session.scalar(select(func.count()).select_from(AttendanceException).where(
            AttendanceException.status.in_(["PENDING_REVIEW", "ASSIGNED", "UNDER_REVIEW"]))),
    }


def reconciliation_rows(session: Session, principal: Principal, run_id: int, category: str | None = None) -> list[dict]:
    if not has_permission(principal, Perm.RECONCILIATION_VIEW):
        raise AuthorizationError("reconciliation not permitted")
    q = select(AttendanceReconciliation).where(AttendanceReconciliation.run_id == run_id).limit(ROW_LIMIT)
    if category:
        q = q.where(AttendanceReconciliation.category == category)
    scope = dept_scope(principal)
    keys = None
    if scope is not None:
        keys = {k for (k,) in session.execute(select(FactAttendanceDaily.employee_key).where(
            FactAttendanceDaily.run_id == run_id, FactAttendanceDaily.department_code.in_(scope or {"__none__"})))}
    return [{"id": r.id, "category": r.category, "source_employee_id": r.source_employee_id, "date": r.attendance_date.isoformat(),
             "bizom": r.bizom_value, "hrms": r.hrms_value, "detail": r.detail}
            for r in session.scalars(q) if keys is None or r.employee_key in keys]
