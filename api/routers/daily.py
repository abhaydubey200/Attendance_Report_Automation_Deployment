"""Upload a day, see its insights, download/preview the reports, (re)send emails."""

from __future__ import annotations

import json
from datetime import date

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from fastapi.responses import HTMLResponse, Response
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from api.deps import get_db, get_settings, require
from core.config import Settings
from daily import employees as emp
from daily import mail, routing, service
from daily.settings_store import get_email_settings
from security.audit import record_activity
from security.authorization import has_permission
from daily.analysis import FileError
from daily.render import file_stem
from database.models.daily import DayUpload, EmailLog
from security.permissions import Perm, Principal

router = APIRouter(tags=["daily"])

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _day(db: Session, report_date: date) -> DayUpload:
    up = service.current_upload(db, report_date)
    if up is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No upload for that date.")
    return up


def _day_payload(db: Session, up: DayUpload, include_rows: bool = True) -> dict:
    insights = json.loads(up.insights)
    emails = [{"scope": e.scope, "recipients": e.recipients, "status": e.status, "mode": e.mode, "error": e.error,
               "sent_at": e.sent_at.isoformat(), "sent_by": e.sent_by}
              for e in db.scalars(select(EmailLog).where(EmailLog.upload_id == up.upload_id).order_by(EmailLog.id))]
    out = {"upload_id": up.upload_id, "report_date": up.report_date.isoformat(), "file": up.original_filename,
           "permission_file": up.permission_filename, "onduty_file": up.onduty_filename,
           "uploaded_by": up.uploaded_by, "uploaded_at": up.uploaded_at.isoformat(), "employees": up.employees,
           "insights": insights, "emails": emails}
    if include_rows:
        out["rows"] = service.rows_for(db, up.upload_id)
    return out


@router.get("/upload/options")
def upload_options(principal: Principal = Depends(require(Perm.UPLOAD_AND_SEND)), settings: Settings = Depends(get_settings),
                   db: Session = Depends(get_db)) -> dict:
    """Defaults for the Upload screen."""
    cfg = get_email_settings(db, settings)
    return {"default_mode": service.default_send_mode(cfg), "wait_for_permission": cfg.wait_for_permission, "mode": cfg.mode,
            "test_recipient": cfg.test_recipient, "test_cc": cfg.test_cc,
            "can_import_master": has_permission(principal, Perm.MANAGE_EMPLOYEES), "employees": len(emp.list_all(db))}


def _import_master(db: Session, settings: Settings, principal: Principal, name: str, data: bytes) -> dict:
    if not has_permission(principal, Perm.MANAGE_EMPLOYEES):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "You are not allowed to import the employee master.")
    try:
        rows = emp.read_master_file(name, data)
    except emp.EmployeeError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"Employee master: {exc}") from None
    result = emp.import_rows(db, rows, principal.username).as_dict()
    try:
        extras = emp.read_routing_extras(name, data)
    except emp.EmployeeError:
        extras = {}
    if extras:
        result["routing"] = routing.apply_workbook(db, settings, extras, principal.username)
    record_activity(db, "EMPLOYEE_IMPORT", "SUCCESS", username=principal.username,
                    detail={k: v for k, v in result.items() if k not in ("problems", "routing")})
    return result


@router.post("/days/upload")
async def upload(master: UploadFile | None = File(None), hrms: UploadFile | None = File(None), permission: UploadFile | None = File(None),
                 onduty: UploadFile | None = File(None),
                 files: list[UploadFile] | None = File(None), file: UploadFile | None = File(None),
                 replace: bool = Form(False), send_mode: str = Form(""),
                 principal: Principal = Depends(require(Perm.UPLOAD_AND_SEND)), settings: Settings = Depends(get_settings),
                 db: Session = Depends(get_db)) -> dict:
    """Up to four datasets at once: the employee master (optional, imported first so routing uses it), and the
    Pocket HRMS Attendance Summary, Permission Report and On Duty Report of one day.
    send_mode: 'auto' = send the emails right away, 'manual' = wait on Approve emails, '' = Settings default."""
    if send_mode not in ("", service.AUTO, service.MANUAL):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "send_mode must be 'auto' or 'manual'.")
    limit = settings.uploads.max_file_size_mb * 1024 * 1024 + 1
    slotted = [(f, kind) for f, kind in ((hrms, "HRMS"), (permission, "PERMISSION"), (onduty, "ONDUTY")) if f is not None]
    generic = [(f, None) for f in (files or []) + ([file] if file else []) if f is not None]
    chosen = slotted + generic
    if master is None and not chosen:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Choose a file to upload.")
    if len(chosen) > 3:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT,
                            "Upload at most three files: the Attendance Summary, the Permission Report and the On Duty Report.")
    master_result = None
    if master is not None:
        master_result = _import_master(db, settings, principal, master.filename or "employees.xlsx", await master.read(limit))
        if not chosen:
            return {"master_import": master_result, "report_date": None, "mail": [], "auto_sent": False,
                    "send_note": "Employee master updated. Upload the attendance files to prepare the emails."}
    payload = [(f.filename or "upload.xlsx", await f.read(limit)) for f, _ in chosen]
    try:
        up, items, note = service.upload_files_and_send(db, settings, payload, principal.username, replace,
                                                         send_mode or None, [k for _, k in chosen])
    except FileError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from None
    except service.AlreadyUploaded as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from None
    cfg = get_email_settings(db, settings)
    sendable = mail.sendable_statuses(cfg)
    return {**_day_payload(db, up, include_rows=False), "send_note": note, "mail": [mail.item_dict(i, sendable) for i in items],
            "auto_sent": any(i.status in mail.DELIVERED for i in items), "master_import": master_result,
            "send_mode": send_mode or service.default_send_mode(cfg)}


@router.get("/days")
def days(_: Principal = Depends(require(Perm.VIEW_INSIGHTS)), db: Session = Depends(get_db)) -> list[dict]:
    out = []
    for up in db.scalars(select(DayUpload).where(DayUpload.is_current.is_(True)).order_by(DayUpload.report_date.desc()).limit(400)):
        s = json.loads(up.insights)["scopes"]["ALL"]["summary"]
        sent = db.scalars(select(EmailLog.status).where(EmailLog.upload_id == up.upload_id)).all()
        out.append({"report_date": up.report_date.isoformat(), "employees": up.employees, "attendance_pct": s["attendance_pct"],
                    "has_hrms": bool(up.stored_path), "has_permission": bool(up.permission_path), "has_onduty": bool(up.onduty_path),
                    "absent": s["counts"]["ABSENT"], "late": s["late"], "emails": len(sent),
                    "email_failed": sum(1 for x in sent if x == "FAILED"), "uploaded_at": up.uploaded_at.isoformat()})
    return out


@router.get("/days/{report_date}")
def day(report_date: date, _: Principal = Depends(require(Perm.VIEW_INSIGHTS)), db: Session = Depends(get_db)) -> dict:
    return _day_payload(db, _day(db, report_date))


def _scope(up: DayUpload, scope: str) -> str:
    try:
        return service.check_scope(up, scope)
    except LookupError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from None


@router.get("/days/{report_date}/excel")
def excel(report_date: date, scope: str = Query("ALL"), _: Principal = Depends(require(Perm.VIEW_INSIGHTS)),
          settings: Settings = Depends(get_settings), db: Session = Depends(get_db)) -> Response:
    up = _day(db, report_date)
    scope = _scope(up, scope)
    content = service.excel_bytes(settings, up, scope, service.rows_for(db, up.upload_id))
    return Response(content, media_type=XLSX,
                    headers={"Content-Disposition": f'attachment; filename="{file_stem(up.report_date, scope)}.xlsx"'})


@router.get("/days/{report_date}/dashboard")
def dashboard(report_date: date, scope: str = Query("ALL"), _: Principal = Depends(require(Perm.VIEW_INSIGHTS)),
              settings: Settings = Depends(get_settings), db: Session = Depends(get_db)) -> Response:
    up = _day(db, report_date)
    scope = _scope(up, scope)
    content = service.dashboard_bytes(settings, up, scope, service.rows_for(db, up.upload_id), db)
    return Response(content, media_type="text/html; charset=utf-8", headers={
        "Content-Disposition": f'attachment; filename="{file_stem(up.report_date, scope)}_dashboard.html"',
        # Self-contained page: its own inline script/styles only, no network access.
        "Content-Security-Policy": "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src data:; sandbox allow-scripts"})


@router.post("/days/{report_date}/recalculate")
def recalculate(report_date: date, principal: Principal = Depends(require(Perm.UPLOAD_AND_SEND)),
                settings: Settings = Depends(get_settings), db: Session = Depends(get_db)) -> dict:
    try:
        up = service.recalculate(db, settings, report_date, principal.username)
    except LookupError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from None
    return _day_payload(db, up, include_rows=False)


@router.get("/emails")
def emails(_: Principal = Depends(require(Perm.VIEW_INSIGHTS)), db: Session = Depends(get_db)) -> list[dict]:
    rows = db.execute(select(EmailLog, DayUpload.report_date).join(DayUpload, DayUpload.upload_id == EmailLog.upload_id)
                      .order_by(EmailLog.id.desc()).limit(500)).all()
    return [{"id": e.id, "report_date": d.isoformat(), "scope": e.scope, "recipients": e.recipients, "subject": e.subject,
             "mode": e.mode, "status": e.status, "error": e.error, "sent_by": e.sent_by, "sent_at": e.sent_at.isoformat()}
            for e, d in rows]
