"""Attendance analytics, reconciliation and exception workflow APIs (PRD 9, 12)."""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from api.deps import get_db, get_settings, require
from core.config import Settings, load_attendance_rules
from database.models.attendance import AttendanceException
from database.models.audit import ExceptionResolutionLog
from data_engine import exception_manager
from reporting import analytics
from security.permissions import Perm, Principal

router = APIRouter(tags=["attendance"])


def _bad(exc: Exception) -> HTTPException:
    return HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))


@router.get("/attendance/summary")
def summary(day: date | None = Query(None, alias="date"), principal: Principal = Depends(require(Perm.DASHBOARD_VIEW)),
            settings: Settings = Depends(get_settings), db: Session = Depends(get_db)) -> dict:
    return analytics.summary(db, principal, load_attendance_rules(settings.config_dir), day)


@router.get("/attendance/trend")
def trend(start: date, end: date, department: str | None = None,
          principal: Principal = Depends(require(Perm.ATTENDANCE_VIEW_AGGREGATE)), settings: Settings = Depends(get_settings),
          db: Session = Depends(get_db)) -> list[dict]:
    try:
        return analytics.trend(db, principal, load_attendance_rules(settings.config_dir), start, end, department)
    except ValueError as exc:
        raise _bad(exc) from None


@router.get("/attendance/daily")
def daily(day: date = Query(..., alias="date"), status_filter: str | None = Query(None, alias="status"),
          department: str | None = None, principal: Principal = Depends(require(Perm.ATTENDANCE_VIEW_EMPLOYEE)),
          db: Session = Depends(get_db)) -> list[dict]:
    statuses = set(status_filter.split(",")) if status_filter else None
    return analytics.employee_rows(db, principal, day, statuses, department)


@router.get("/attendance/employee/{employee_code}")
def employee(employee_code: str, start: date, end: date, principal: Principal = Depends(require(Perm.ATTENDANCE_VIEW_EMPLOYEE)),
             db: Session = Depends(get_db)) -> dict:
    try:
        return analytics.employee_history(db, principal, employee_code, start, end)
    except LookupError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Employee not found") from None
    except ValueError as exc:
        raise _bad(exc) from None


@router.get("/reconciliation")
def reconciliation(day: date | None = Query(None, alias="date"), category: str | None = None,
                   principal: Principal = Depends(require(Perm.RECONCILIATION_VIEW)), db: Session = Depends(get_db)) -> dict:
    run = analytics.current_run(db, day)
    if run is None:
        return {"run": None, "rows": []}
    return {"run": analytics.run_info(run), "rows": analytics.reconciliation_rows(db, principal, run.run_id, category)}


def _exc_row(e: AttendanceException) -> dict:
    import json
    return {"exception_id": e.exception_id, "run_id": e.run_id, "source_employee_id": e.source_employee_id,
            "employee_key": e.employee_key, "department_code": e.department_code, "date": e.attendance_date.isoformat(),
            "category": e.category, "severity": e.severity, "source_values": json.loads(e.source_values), "status": e.status,
            "assigned_to": e.assigned_to, "resolution": e.resolution, "resolved_status": e.resolved_status,
            "resolution_comment": e.resolution_comment, "resolved_by": e.resolved_by,
            "resolved_at": e.resolved_at.isoformat() if e.resolved_at else None, "detected_at": e.detected_at.isoformat()}


@router.get("/exceptions")
def exceptions(status_filter: str | None = Query(None, alias="status"), category: str | None = None,
               day: date | None = Query(None, alias="date"), principal: Principal = Depends(require(Perm.RECONCILIATION_VIEW)),
               db: Session = Depends(get_db)) -> list[dict]:
    q = select(AttendanceException).order_by(AttendanceException.exception_id.desc()).limit(1000)
    if status_filter == "OPEN":
        q = q.where(AttendanceException.status.in_(exception_manager.OPEN))
    elif status_filter:
        q = q.where(AttendanceException.status == status_filter)
    if category:
        q = q.where(AttendanceException.category == category)
    if day:
        q = q.where(AttendanceException.attendance_date == day)
    scope = analytics.dept_scope(principal)
    if scope is not None:
        q = q.where(AttendanceException.department_code.in_(scope or {"__none__"}))
    return [_exc_row(e) for e in db.scalars(q)]


@router.get("/exceptions/{exception_id}/history")
def exception_history(exception_id: int, principal: Principal = Depends(require(Perm.RECONCILIATION_VIEW)),
                      db: Session = Depends(get_db)) -> list[dict]:
    e = db.get(AttendanceException, exception_id)
    scope = analytics.dept_scope(principal)
    if e is None or (scope is not None and e.department_code not in scope):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Exception not found")
    return [{"from": l.from_status, "to": l.to_status, "actor": l.actor, "comment": l.comment, "at": l.occurred_at.isoformat()}
            for l in db.scalars(select(ExceptionResolutionLog).where(ExceptionResolutionLog.exception_id == exception_id)
                                .order_by(ExceptionResolutionLog.id))]


class ActionIn(BaseModel):
    action: str                         # ASSIGN | START | RESOLVE
    assignee: str | None = None
    decision: str | None = None         # ADJUST | NO_CHANGE | REJECT
    adjusted_status: str | None = None
    comment: str | None = None


@router.post("/exceptions/{exception_id}/action")
def exception_action(exception_id: int, body: ActionIn, principal: Principal = Depends(require(Perm.RECONCILIATION_RESOLVE)),
                     db: Session = Depends(get_db)) -> dict:
    try:
        if body.action == "ASSIGN":
            e = exception_manager.assign(db, exception_id, body.assignee or principal.username, principal)
        elif body.action == "START":
            e = exception_manager.start_review(db, exception_id, principal)
        elif body.action == "RESOLVE":
            e = exception_manager.resolve(db, exception_id, principal, decision=body.decision or "", comment=body.comment or "",
                                          adjusted_status=body.adjusted_status)
        else:
            raise exception_manager.ExceptionWorkflowError("Unknown action.")
    except LookupError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Exception not found") from None
    except exception_manager.ExceptionWorkflowError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from None
    return _exc_row(e)
