"""Employee master: list (filtered on screen), add, edit, mark Left / restore, history, Excel import/export."""

from __future__ import annotations

import io
from datetime import date

import xlsxwriter
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

from api.deps import get_db, get_settings, require
from core.config import Settings
from daily import employees as emp
from security.audit import record_activity
from security.permissions import Perm, Principal

router = APIRouter(tags=["employees"])
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


class EmployeeIn(BaseModel):
    code: str | None = None
    name: str | None = None
    department: str | None = None
    date_of_joining: str | None = None
    hod_name: str | None = None
    hod_email: str | None = None
    team_lead_email: str | None = None
    reporting_manager: str | None = None


class LeftIn(BaseModel):
    exit_date: date


def _bad(exc: Exception, code: int = status.HTTP_422_UNPROCESSABLE_CONTENT) -> HTTPException:
    return HTTPException(code, str(exc).strip("'\""))


@router.get("/employees")
def list_employees(_: Principal = Depends(require(Perm.VIEW_INSIGHTS)), db: Session = Depends(get_db)) -> dict:
    return {"employees": [emp.to_dict(e) for e in emp.list_all(db)], "summary": emp.summary(db)}


@router.post("/employees", status_code=status.HTTP_201_CREATED)
def create_employee(body: EmployeeIn, principal: Principal = Depends(require(Perm.MANAGE_EMPLOYEES)),
                    db: Session = Depends(get_db)) -> dict:
    try:
        e = emp.create(db, body.model_dump(), principal.username)
    except emp.EmployeeError as exc:
        raise _bad(exc) from None
    record_activity(db, "EMPLOYEE_CREATE", "SUCCESS", username=principal.username, detail={"code": e.code})
    return emp.to_dict(e)


@router.put("/employees/{code}")
def update_employee(code: str, body: EmployeeIn, principal: Principal = Depends(require(Perm.MANAGE_EMPLOYEES)),
                    db: Session = Depends(get_db)) -> dict:
    data = body.model_dump(exclude_unset=True)
    data.pop("code", None)                      # the code identifies the employee and is not editable
    try:
        e = emp.update(db, code, data, principal.username)
    except LookupError as exc:
        raise _bad(exc, status.HTTP_404_NOT_FOUND) from None
    except emp.EmployeeError as exc:
        raise _bad(exc) from None
    record_activity(db, "EMPLOYEE_UPDATE", "SUCCESS", username=principal.username, detail={"code": e.code})
    return emp.to_dict(e)


@router.post("/employees/{code}/left")
def mark_left(code: str, body: LeftIn, principal: Principal = Depends(require(Perm.MANAGE_EMPLOYEES)),
              db: Session = Depends(get_db)) -> dict:
    try:
        e = emp.mark_left(db, code, body.exit_date, principal.username)
    except LookupError as exc:
        raise _bad(exc, status.HTTP_404_NOT_FOUND) from None
    record_activity(db, "EMPLOYEE_LEFT", "SUCCESS", username=principal.username,
                    detail={"code": e.code, "exit_date": body.exit_date.isoformat()})
    return emp.to_dict(e)


@router.post("/employees/{code}/restore")
def restore(code: str, principal: Principal = Depends(require(Perm.MANAGE_EMPLOYEES)), db: Session = Depends(get_db)) -> dict:
    try:
        e = emp.restore(db, code, principal.username)
    except LookupError as exc:
        raise _bad(exc, status.HTTP_404_NOT_FOUND) from None
    record_activity(db, "EMPLOYEE_RESTORE", "SUCCESS", username=principal.username, detail={"code": e.code})
    return emp.to_dict(e)


@router.get("/employees/{code}/history")
def history(code: str, _: Principal = Depends(require(Perm.VIEW_INSIGHTS)), db: Session = Depends(get_db)) -> list[dict]:
    return emp.history(db, code)


@router.post("/employees/import")
async def import_file(file: UploadFile = File(...), principal: Principal = Depends(require(Perm.MANAGE_EMPLOYEES)),
                      settings: Settings = Depends(get_settings), db: Session = Depends(get_db)) -> dict:
    limit = settings.uploads.max_file_size_mb * 1024 * 1024
    data = await file.read(limit + 1)
    if len(data) > limit:
        raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, f"File is larger than {settings.uploads.max_file_size_mb} MB.")
    try:
        rows = emp.read_master_file(file.filename or "employees.xlsx", data)
    except emp.EmployeeError as exc:
        raise _bad(exc) from None
    result = emp.import_rows(db, rows, principal.username)
    record_activity(db, "EMPLOYEE_IMPORT", "SUCCESS", username=principal.username,
                    detail={k: v for k, v in result.as_dict().items() if k != "problems"})
    return result.as_dict()


@router.get("/employees/export")
def export(_: Principal = Depends(require(Perm.VIEW_INSIGHTS)), db: Session = Depends(get_db)) -> Response:
    """Same columns as HR's import file (plus Status / Last working day), so it can be edited and re-imported."""
    head = ["EMPLOYEE CODE", "Employee Name", "Department", "DOJ", "HOD", "Email ID - HOD", "Sub split ID",
            "Reporting Manager", "Team", "Status", "Last working day"]
    buf = io.BytesIO()
    wb = xlsxwriter.Workbook(buf, {"in_memory": True, "strings_to_formulas": False, "strings_to_urls": False})
    ws = wb.add_worksheet("Employees")
    bold = wb.add_format({"bold": True, "bg_color": "#835415", "font_color": "#FFFFFF"})
    for j, h in enumerate(head):
        ws.write(0, j, h, bold)
    for i, e in enumerate(emp.list_all(db), start=1):
        d = emp.to_dict(e)
        vals = [d["code"], d["name"], d["department"], d["date_of_joining"] or "", d["hod_name"], d["hod_email"],
                d["team_lead_email"], d["reporting_manager"], d["team"], "Left" if d["status"] == emp.LEFT else "Active",
                d["exit_date"] or ""]
        for j, v in enumerate(vals):
            ws.write_string(i, j, str(v))
    ws.set_column(0, 0, 14)
    ws.set_column(1, 10, 22)
    ws.freeze_panes(1, 2)
    wb.close()
    return Response(buf.getvalue(), media_type=XLSX,
                    headers={"Content-Disposition": f'attachment; filename="APIS_Employees_{date.today():%Y-%m-%d}.xlsx"'})
