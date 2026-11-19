"""Module 2 - Field Sales attendance (Bizom) API, all under /api/v1/sales. Independent of Module 1's routes."""

from __future__ import annotations

import json
from datetime import date

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from fastapi.responses import HTMLResponse, Response
from pydantic import BaseModel, ValidationError
from sqlalchemy.orm import Session

from api.deps import get_db, get_settings, require
from core.config import Settings
from daily.branding import inline_logo_for_browser
from database.models.sales import SalesMailItem
from sales import bizom, mail, report, service, staff
from sales.config import SalesEmail, SalesRules, get_email, get_rules, save_email, save_rules
from security.permissions import Perm, Principal

router = APIRouter(prefix="/sales", tags=["sales"])
PREVIEW_CSP = "default-src 'none'; style-src 'unsafe-inline'; img-src data:; sandbox; frame-ancestors 'self'"
DASHBOARD_CSP = "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src data:; sandbox allow-scripts"
XLSX = mail.XLSX


def _upload_or_404(db: Session, d: date):
    up = service.current_upload(db, d)
    if up is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"{d:%d-%b-%Y} has not been uploaded.")
    return up


def _day(db: Session, up) -> dict:
    s = json.loads(up.summary)
    rows = service.rows_for(db, up.upload_id)
    view = report.build_view(rows, s, "hr", "HR", up.report_date)
    return {"report_date": up.report_date.isoformat(), "people": up.people, "summary": s,
            "files": {"attendance": up.attendance_file, "eod": up.eod_file, "calls": up.calls_file},
            "uploaded_by": up.uploaded_by, "uploaded_at": up.uploaded_at.isoformat(),
            "rows": view["people"], "warnings": view["warnings"], "teams": view["teams"],
            "mail": [mail.item_dict(i) for i in mail.items_for(db, up.report_date)]}


# ---------------------------------------------------------------- days
@router.get("/days")
def days(_: Principal = Depends(require(Perm.VIEW_INSIGHTS)), db: Session = Depends(get_db)) -> list[dict]:
    return service.days(db)


@router.post("/upload")
async def upload(files: list[UploadFile] = File(...), replace: bool = Form(False),
                 principal: Principal = Depends(require(Perm.UPLOAD_AND_SEND)), db: Session = Depends(get_db)) -> dict:
    if len(files) > 3:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Upload at most three Bizom reports: Attendance, Attendance & EOD, Call Variance.")
    payload = [(f.filename or "bizom.csv", await f.read(service.MAX_MB * 1024 * 1024 + 1)) for f in files]
    try:
        up = service.process(db, payload, principal.username, replace)
    except service.AlreadyUploaded as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from None
    except service.UploadError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from None
    return _day(db, up)


@router.get("/days/{report_date}")
def day(report_date: date, _: Principal = Depends(require(Perm.VIEW_INSIGHTS)), db: Session = Depends(get_db)) -> dict:
    return _day(db, _upload_or_404(db, report_date))


@router.get("/days/{report_date}/excel")
def day_excel(report_date: date, _: Principal = Depends(require(Perm.VIEW_INSIGHTS)), db: Session = Depends(get_db)) -> Response:
    up = _upload_or_404(db, report_date)
    v = report.build_view(service.rows_for(db, up.upload_id), json.loads(up.summary), "hr", "HR", up.report_date)
    return Response(report.excel(v), media_type=XLSX, headers={"Content-Disposition": f'attachment; filename="{v["stem"]}.xlsx"'})


@router.get("/days/{report_date}/dashboard")
def day_dashboard(report_date: date, _: Principal = Depends(require(Perm.VIEW_INSIGHTS)), db: Session = Depends(get_db)) -> Response:
    up = _upload_or_404(db, report_date)
    v = report.build_view(service.rows_for(db, up.upload_id), json.loads(up.summary), "company", "HR", up.report_date)
    return Response(report.dashboard(v), media_type="text/html", headers={
        "Content-Disposition": f'attachment; filename="{v["stem"]}_dashboard.html"', "Content-Security-Policy": DASHBOARD_CSP})


# ---------------------------------------------------------------- emails
class ApproveIn(BaseModel):
    ids: list[int] | None = None


def _outbox(settings: Settings):
    return settings.storage.area("sales_outbox")


@router.get("/days/{report_date}/mail")
def day_mail(report_date: date, _: Principal = Depends(require(Perm.VIEW_INSIGHTS)), db: Session = Depends(get_db)) -> dict:
    cfg = get_email(db)
    return {"report_date": report_date.isoformat(), "mode": cfg.mode, "testing": cfg.test_recipient,
            "items": [mail.item_dict(i) for i in mail.items_for(db, report_date)]}


@router.post("/days/{report_date}/mail/plan")
def replan(report_date: date, _: Principal = Depends(require(Perm.UPLOAD_AND_SEND)), db: Session = Depends(get_db)) -> dict:
    up = _upload_or_404(db, report_date)
    for i in mail.items_for(db, report_date):
        if i.status in mail.REPLACEABLE:
            i.status, i.note = mail.SUPERSEDED, "Prepared again."
    mail.plan(db, up)
    return day_mail(report_date, _, db)


@router.post("/days/{report_date}/mail/approve")
def approve(report_date: date, body: ApproveIn, principal: Principal = Depends(require(Perm.UPLOAD_AND_SEND)),
            settings: Settings = Depends(get_settings), db: Session = Depends(get_db)) -> dict:
    todo = [i for i in mail.items_for(db, report_date) if i.status in (mail.PENDING, mail.FAILED) and (body.ids is None or i.id in body.ids)]
    done = mail.send_items(db, todo, principal.username, _outbox(settings))
    return {**day_mail(report_date, principal, db), "sent_now": len(done)}


def _item(db: Session, item_id: int) -> SalesMailItem:
    item = db.get(SalesMailItem, item_id)
    if item is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Email not found.")
    return item


@router.post("/mail/{item_id}/resend")
def resend(item_id: int, principal: Principal = Depends(require(Perm.UPLOAD_AND_SEND)), settings: Settings = Depends(get_settings),
           db: Session = Depends(get_db)) -> dict:
    item = _item(db, item_id)
    mail.send_items(db, [item], principal.username, _outbox(settings), force=True)
    return mail.item_dict(item)


@router.get("/mail/{item_id}/preview", response_class=HTMLResponse)
def preview(item_id: int, _: Principal = Depends(require(Perm.VIEW_INSIGHTS)), db: Session = Depends(get_db)) -> HTMLResponse:
    html, _text, _files = mail.render(db, _item(db, item_id))
    return HTMLResponse(inline_logo_for_browser(html), headers={"Content-Security-Policy": PREVIEW_CSP})


@router.get("/mail/{item_id}/attachment/{kind}")
def attachment(item_id: int, kind: str, _: Principal = Depends(require(Perm.VIEW_INSIGHTS)), db: Session = Depends(get_db)) -> Response:
    _html, _text, files = mail.render(db, _item(db, item_id))
    want = ".xlsx" if kind == "excel" else "_dashboard.html" if kind == "dashboard" else None
    f = next((f for f in files if want and f.filename.endswith(want)), None)
    if f is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Attachment not found.")
    headers = {"Content-Disposition": f'attachment; filename="{f.filename}"'}
    if kind == "dashboard":
        headers["Content-Security-Policy"] = DASHBOARD_CSP
    return Response(f.content, media_type=f.mime, headers=headers)


# ---------------------------------------------------------------- staff list
@router.get("/staff")
def staff_list(_: Principal = Depends(require(Perm.VIEW_INSIGHTS)), db: Session = Depends(get_db)) -> dict:
    from sqlalchemy import select

    from database.models.sales import SalesEmployee
    return {"summary": staff.summary(db), "staff": [staff.to_dict(e) for e in db.scalars(select(SalesEmployee).order_by(SalesEmployee.name))]}


@router.post("/staff/import")
async def staff_import(file: UploadFile = File(...), principal: Principal = Depends(require(Perm.MANAGE_EMPLOYEES)),
                       db: Session = Depends(get_db)) -> dict:
    data = await file.read(10 * 1024 * 1024 + 1)
    try:
        rows = bizom.read_rows(data, file.filename or "staff.xlsx")
        return staff.import_rows(db, [[("" if c is None else str(c)) for c in r] for r in rows], principal.username, file.filename or "upload")
    except (bizom.BizomError, staff.StaffError) as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from None


@router.get("/staff/export")
def staff_export(_: Principal = Depends(require(Perm.VIEW_INSIGHTS)), db: Session = Depends(get_db)) -> Response:
    return Response(staff.export_xlsx(db), media_type=XLSX, headers={"Content-Disposition": 'attachment; filename="Field_Sales_Staff.xlsx"'})


class LeftIn(BaseModel):
    exit_date: date | None = None


@router.post("/staff/{code}/left")
def staff_left(code: str, body: LeftIn, principal: Principal = Depends(require(Perm.MANAGE_EMPLOYEES)), db: Session = Depends(get_db)) -> dict:
    try:
        return staff.to_dict(staff.mark_left(db, code, body.exit_date, principal.username))
    except LookupError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not on the staff list.") from None


@router.post("/staff/{code}/restore")
def staff_restore(code: str, principal: Principal = Depends(require(Perm.MANAGE_EMPLOYEES)), db: Session = Depends(get_db)) -> dict:
    try:
        return staff.to_dict(staff.restore(db, code, principal.username))
    except LookupError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not on the staff list.") from None


# ---------------------------------------------------------------- settings
@router.get("/settings")
def get_settings_(_: Principal = Depends(require(Perm.VIEW_INSIGHTS)), db: Session = Depends(get_db)) -> dict:
    return {"rules": get_rules(db).model_dump(), "email": get_email(db).model_dump()}


@router.put("/settings/rules")
def put_rules(body: dict, principal: Principal = Depends(require(Perm.MANAGE_SETTINGS)), db: Session = Depends(get_db)) -> dict:
    try:
        rules = SalesRules.model_validate({**get_rules(db).model_dump(), **body})
    except ValidationError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, exc.errors()[0]["msg"]) from None
    return save_rules(db, rules, principal.username).model_dump()


@router.put("/settings/email")
def put_email(body: dict, principal: Principal = Depends(require(Perm.MANAGE_SETTINGS)), db: Session = Depends(get_db)) -> dict:
    try:
        email = SalesEmail.model_validate({**get_email(db).model_dump(), **body})
    except ValidationError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, exc.errors()[0]["msg"]) from None
    return save_email(db, email, principal.username).model_dump()
