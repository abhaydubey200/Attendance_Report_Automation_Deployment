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
from daily import service
from daily.analysis import FileError
from daily.render import file_stem
from daily.settings_store import ALL, get_email_settings
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
           "bizom_file": up.bizom_filename,
           "uploaded_by": up.uploaded_by, "uploaded_at": up.uploaded_at.isoformat(), "employees": up.employees,
           "insights": insights, "emails": emails}
    if include_rows:
        out["rows"] = service.rows_for(db, up.upload_id)
    return out


@router.post("/days/upload")
async def upload(files: list[UploadFile] | None = File(None), file: UploadFile | None = File(None), replace: bool = Form(False),
                 principal: Principal = Depends(require(Perm.UPLOAD_AND_SEND)), settings: Settings = Depends(get_settings),
                 db: Session = Depends(get_db)) -> dict:
    """One day's Pocket HRMS Attendance Summary and/or Bizom attendance report (detected by their columns)."""
    chosen = [f for f in (files or []) + ([file] if file else []) if f is not None]
    if not chosen:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Choose a file to upload.")
    if len(chosen) > 2:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Upload at most two files: Pocket HRMS and Bizom.")
    limit = settings.uploads.max_file_size_mb * 1024 * 1024 + 1
    payload = [(f.filename or "upload.xlsx", await f.read(limit)) for f in chosen]
    try:
        up, outcomes, note = service.upload_files_and_send(db, settings, payload, principal.username, replace)
    except FileError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from None
    except service.AlreadyUploaded as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from None
    return {**_day_payload(db, up, include_rows=False),
            "auto_sent": outcomes is not None, "send_note": note, "email_results": [o.as_dict() for o in outcomes or []]}


@router.get("/days")
def days(_: Principal = Depends(require(Perm.VIEW_INSIGHTS)), db: Session = Depends(get_db)) -> list[dict]:
    out = []
    for up in db.scalars(select(DayUpload).where(DayUpload.is_current.is_(True)).order_by(DayUpload.report_date.desc()).limit(400)):
        s = json.loads(up.insights)["scopes"]["ALL"]["summary"]
        sent = db.scalars(select(EmailLog.status).where(EmailLog.upload_id == up.upload_id)).all()
        out.append({"report_date": up.report_date.isoformat(), "employees": up.employees, "attendance_pct": s["attendance_pct"],
                    "has_hrms": bool(up.stored_path), "has_bizom": bool(up.bizom_path),
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
def excel(report_date: date, scope: str = Query(ALL), _: Principal = Depends(require(Perm.VIEW_INSIGHTS)),
          settings: Settings = Depends(get_settings), db: Session = Depends(get_db)) -> Response:
    up = _day(db, report_date)
    scope = _scope(up, scope)
    content = service.excel_bytes(settings, up, scope, service.rows_for(db, up.upload_id))
    return Response(content, media_type=XLSX,
                    headers={"Content-Disposition": f'attachment; filename="{file_stem(up.report_date, scope)}.xlsx"'})


@router.get("/days/{report_date}/dashboard")
def dashboard(report_date: date, scope: str = Query(ALL), _: Principal = Depends(require(Perm.VIEW_INSIGHTS)),
              settings: Settings = Depends(get_settings), db: Session = Depends(get_db)) -> Response:
    up = _day(db, report_date)
    scope = _scope(up, scope)
    content = service.dashboard_bytes(settings, up, scope, service.rows_for(db, up.upload_id))
    return Response(content, media_type="text/html; charset=utf-8", headers={
        "Content-Disposition": f'attachment; filename="{file_stem(up.report_date, scope)}_dashboard.html"',
        # Self-contained page: its own inline script/styles only, no network access.
        "Content-Security-Policy": "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src data:; sandbox allow-scripts"})


@router.get("/days/{report_date}/email-preview", response_class=HTMLResponse)
def email_preview(report_date: date, scope: str = Query(ALL), _: Principal = Depends(require(Perm.VIEW_INSIGHTS)),
                  settings: Settings = Depends(get_settings), db: Session = Depends(get_db)) -> HTMLResponse:
    up = _day(db, report_date)
    subject, html = service.email_preview(db, settings, up, _scope(up, scope))
    return HTMLResponse(html, headers={"X-Email-Subject": subject.encode("ascii", "replace").decode(),
                                       "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; img-src data:; sandbox; frame-ancestors 'self'"})


class SendIn(BaseModel):
    scopes: list[str] | None = None


@router.post("/days/{report_date}/send")
def send(report_date: date, body: SendIn, principal: Principal = Depends(require(Perm.UPLOAD_AND_SEND)),
         settings: Settings = Depends(get_settings), db: Session = Depends(get_db)) -> dict:
    up = _day(db, report_date)
    scopes = [_scope(up, s) for s in body.scopes] if body.scopes else None
    outcomes = service.send_reports(db, settings, up, principal.username, scopes)
    return {"mode": get_email_settings(db, settings).mode, "email_results": [o.as_dict() for o in outcomes]}


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
