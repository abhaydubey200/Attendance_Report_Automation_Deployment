"""Organisation data and employee identity mapping (PRD 7)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from api.deps import current_principal, get_db, require
from core.exceptions import AuthorizationError
from database.models.hr import DimDepartment, DimEmployee, EmployeeOrgHistory, EmployeeSourceMapping, HolidayCalendar, ReportingHierarchy
from data_engine.employee_mapper import resolve_mapping
from security.authorization import has_permission
from security.permissions import Perm, Principal

router = APIRouter(tags=["organisation"])


def _mapping_or_resolve(principal: Principal = Depends(current_principal)) -> Principal:
    if not (has_permission(principal, Perm.ADMIN_MAPPING) or has_permission(principal, Perm.RECONCILIATION_RESOLVE)):
        raise AuthorizationError("mapping not permitted")
    return principal


@router.get("/departments")
def departments(_: Principal = Depends(require(Perm.ADMIN_MAPPING)), db: Session = Depends(get_db)) -> list[dict]:
    return [{"department_code": d.department_code, "department_name": d.department_name, "parent": d.parent_department_code,
             "hod_employee_code": d.hod_employee_code, "is_active": d.is_active, "source_upload_id": d.source_upload_id}
            for d in db.scalars(select(DimDepartment).order_by(DimDepartment.department_code))]


@router.get("/employees")
def employees(search: str = "", _: Principal = Depends(_mapping_or_resolve), db: Session = Depends(get_db)) -> list[dict]:
    q = select(DimEmployee).order_by(DimEmployee.employee_code).limit(200)
    if search.strip():
        like = f"%{search.strip()[:50]}%"
        q = q.where(or_(DimEmployee.employee_code.ilike(like), DimEmployee.employee_name.ilike(like)))
    return [{"employee_key": e.employee_key, "employee_code": e.employee_code, "employee_name": e.employee_name,
             "department_code": e.department_code, "location_code": e.location_code, "designation": e.designation,
             "employment_status": e.employment_status, "joining_date": e.joining_date.isoformat() if e.joining_date else None,
             "exit_date": e.exit_date.isoformat() if e.exit_date else None} for e in db.scalars(q)]


@router.get("/employees/{employee_key}/org-history")
def org_history(employee_key: int, _: Principal = Depends(require(Perm.ADMIN_MAPPING)), db: Session = Depends(get_db)) -> list[dict]:
    return [{"department_code": h.department_code, "location_code": h.location_code, "effective_from": h.effective_from.isoformat(),
             "effective_to": h.effective_to.isoformat() if h.effective_to else None}
            for h in db.scalars(select(EmployeeOrgHistory).where(EmployeeOrgHistory.employee_key == employee_key)
                                .order_by(EmployeeOrgHistory.effective_from))]


@router.get("/hierarchy")
def hierarchy(_: Principal = Depends(require(Perm.ADMIN_RULES)), db: Session = Depends(get_db)) -> list[dict]:
    return [{"employee_code": h.employee_code, "manager_code": h.manager_code, "effective_from": h.effective_from.isoformat(),
             "effective_to": h.effective_to.isoformat() if h.effective_to else None}
            for h in db.scalars(select(ReportingHierarchy).order_by(ReportingHierarchy.employee_code, ReportingHierarchy.effective_from).limit(2000))]


@router.get("/holidays")
def holidays(_: Principal = Depends(require(Perm.ADMIN_RULES)), db: Session = Depends(get_db)) -> list[dict]:
    return [{"date": h.holiday_date.isoformat(), "name": h.holiday_name, "location_code": h.location_code}
            for h in db.scalars(select(HolidayCalendar).order_by(HolidayCalendar.holiday_date))]


@router.get("/mappings")
def mappings(status_filter: str | None = None, _: Principal = Depends(_mapping_or_resolve), db: Session = Depends(get_db)) -> list[dict]:
    q = select(EmployeeSourceMapping).order_by(EmployeeSourceMapping.status, EmployeeSourceMapping.source_system,
                                               EmployeeSourceMapping.source_employee_id).limit(2000)
    if status_filter:
        q = q.where(EmployeeSourceMapping.status == status_filter)
    emps = {e.employee_key: e for e in db.scalars(select(DimEmployee))}

    def label(key):
        e = emps.get(key)
        return f"{e.employee_code} - {e.employee_name or ''}".strip(" -") if e else None

    return [{"mapping_id": m.mapping_id, "source_system": m.source_system, "source_employee_id": m.source_employee_id,
             "source_employee_name": m.source_employee_name, "status": m.status, "method": m.method,
             "employee_key": m.employee_key, "employee": label(m.employee_key),
             "suggested_employee_key": m.suggested_employee_key, "suggested_employee": label(m.suggested_employee_key),
             "confidence": m.confidence, "reviewed_by": m.reviewed_by} for m in db.scalars(q)]


class ResolveIn(BaseModel):
    employee_key: int | None = None
    reject: bool = False


@router.post("/mappings/{mapping_id}/resolve")
def resolve(mapping_id: int, body: ResolveIn, principal: Principal = Depends(_mapping_or_resolve), db: Session = Depends(get_db)) -> dict:
    try:
        m = resolve_mapping(db, mapping_id, body.employee_key, principal.username, reject=body.reject)
    except LookupError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Mapping not found") from None
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from None
    return {"mapping_id": m.mapping_id, "status": m.status}
