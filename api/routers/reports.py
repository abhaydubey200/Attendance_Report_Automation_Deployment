"""Attendance reports over a date range: one employee, or many employees by filter (with Excel export)."""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import Response
from sqlalchemy.orm import Session

from api.deps import get_db, get_settings, require
from core.config import Settings
from daily import reports
from daily.settings_store import get_rules
from security.permissions import Perm, Principal

router = APIRouter(tags=["reports"])
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _filters(db: Session, start: date | None, end: date | None, **kw) -> reports.Filters:
    d_start, d_end = reports.default_range(db)
    f = reports.Filters(start=start or d_start, end=end or d_end, **{k: (v or "").strip() for k, v in kw.items()})
    try:
        f.check()
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from None
    return f


def common(start: date | None = Query(None, alias="from"), end: date | None = Query(None, alias="to"), hod: str = "",
           department: str = "", team: str = "", manager: str = "", category: str = "", status_: str = Query("", alias="status"),
           source: str = "", q: str = "", db: Session = Depends(get_db)) -> reports.Filters:
    return _filters(db, start, end, hod=hod, department=department, team=team, manager=manager, category=category,
                    status=status_, source=source, q=q)


@router.get("/reports/attendance")
def attendance(f: reports.Filters = Depends(common), days: bool = False, principal: Principal = Depends(require(Perm.VIEW_INSIGHTS)),
               settings: Settings = Depends(get_settings), db: Session = Depends(get_db)) -> dict:
    out = reports.attendance_report(db, f, get_rules(db, settings), with_days=days)
    if days and len(out["days"]) > 5000:
        out["days"], out["days_truncated"] = out["days"][:5000], True
    return out


@router.get("/reports/attendance/excel")
def attendance_xlsx(f: reports.Filters = Depends(common), principal: Principal = Depends(require(Perm.VIEW_INSIGHTS)),
                    settings: Settings = Depends(get_settings), db: Session = Depends(get_db)) -> Response:
    report = reports.attendance_report(db, f, get_rules(db, settings), with_days=True)
    content = reports.attendance_excel(settings.app.company, report, f, settings.app.date_format)
    return Response(content, media_type=XLSX, headers={
        "Content-Disposition": f'attachment; filename="Attendance_{f.start:%Y-%m-%d}_to_{f.end:%Y-%m-%d}.xlsx"'})


def _employee(db: Session, settings: Settings, code: str, start: date | None, end: date | None) -> dict:
    f = _filters(db, start, end)
    try:
        return reports.employee_report(db, code, f.start, f.end, get_rules(db, settings))
    except LookupError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from None


@router.get("/reports/employee/{code}")
def employee(code: str, start: date | None = Query(None, alias="from"), end: date | None = Query(None, alias="to"),
             principal: Principal = Depends(require(Perm.VIEW_INSIGHTS)), settings: Settings = Depends(get_settings),
             db: Session = Depends(get_db)) -> dict:
    return _employee(db, settings, code, start, end)


@router.get("/reports/employee/{code}/excel")
def employee_xlsx(code: str, start: date | None = Query(None, alias="from"), end: date | None = Query(None, alias="to"),
                  principal: Principal = Depends(require(Perm.VIEW_INSIGHTS)), settings: Settings = Depends(get_settings),
                  db: Session = Depends(get_db)) -> Response:
    report = _employee(db, settings, code, start, end)
    content = reports.employee_excel(settings.app.company, report, settings.app.date_format)
    safe = "".join(ch for ch in report["employee"]["code"] if ch.isalnum())
    return Response(content, media_type=XLSX, headers={
        "Content-Disposition": f'attachment; filename="Attendance_{safe}_{report["from"]}_to_{report["to"]}.xlsx"'})
