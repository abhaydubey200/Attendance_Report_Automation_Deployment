"""Automation screen: job history, run the daily job / backup now, month-end reports and the guarded cleanup."""

from __future__ import annotations

import json
import datetime as dt
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from api.deps import get_db, get_engine, get_settings, require
from core.config import Settings
from daily import jobs, mail, monthly
from database.models.daily import MonthlySummary
from security.permissions import Perm, Principal

router = APIRouter(tags=["automation"])
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _locked(exc: Exception) -> HTTPException:
    return HTTPException(status.HTTP_409_CONFLICT, str(exc))


@router.get("/jobs")
def job_history(_: Principal = Depends(require(Perm.VIEW_INSIGHTS)), settings: Settings = Depends(get_settings),
                db: Session = Depends(get_db)) -> dict:
    return {"runs": jobs.history(db), "inbox": str(settings.jobs.inbox_dir), "yesterday": jobs.yesterday_ist().isoformat(),
            "keep_months": settings.jobs.keep_months, "backup_keep_days": settings.jobs.backup_keep_days,
            "database": settings.database.backend, "previous_month": monthly.previous_month()}


class DailyIn(BaseModel):
    report_date: dt.date | None = None
    send_mode: str | None = None


@router.post("/jobs/daily")
def run_daily(body: DailyIn, principal: Principal = Depends(require(Perm.UPLOAD_AND_SEND)), settings: Settings = Depends(get_settings),
              engine: Engine = Depends(get_engine)) -> dict:
    if body.send_mode not in (None, "auto", "manual"):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "send_mode must be auto or manual.")
    try:
        return jobs.run_daily(settings, engine, body.report_date, mode=body.send_mode, trigger="MANUAL", actor=principal.username)
    except jobs.JobLocked as exc:
        raise _locked(exc) from None
    except Exception as exc:  # recorded in the job history; shown to the user
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, f"The daily job failed: {type(exc).__name__}: {exc}") from None


@router.post("/jobs/backup")
def run_backup(principal: Principal = Depends(require(Perm.MANAGE_SETTINGS)), settings: Settings = Depends(get_settings),
               engine: Engine = Depends(get_engine)) -> dict:
    try:
        return jobs.backup(settings, engine, trigger="MANUAL", actor=principal.username)
    except jobs.JobLocked as exc:
        raise _locked(exc) from None
    except Exception as exc:
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, f"Backup failed: {type(exc).__name__}: {exc}") from None


@router.get("/monthly")
def monthly_list(_: Principal = Depends(require(Perm.VIEW_INSIGHTS)), db: Session = Depends(get_db)) -> list[dict]:
    return monthly.summaries(db)


class MonthlyIn(BaseModel):
    month: str
    send_mode: str | None = None


def _month(value: str) -> str:
    try:
        monthly.month_bounds(value)
    except (ValueError, TypeError):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Month must look like 2026-11.") from None
    return value


@router.post("/monthly")
def monthly_generate(body: MonthlyIn, principal: Principal = Depends(require(Perm.UPLOAD_AND_SEND)),
                     settings: Settings = Depends(get_settings), engine: Engine = Depends(get_engine)) -> dict:
    if body.send_mode not in (None, "auto", "manual"):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "send_mode must be auto or manual.")
    try:
        return monthly.generate(settings, engine, _month(body.month), body.send_mode, trigger="MANUAL", actor=principal.username)
    except jobs.JobLocked as exc:
        raise _locked(exc) from None


@router.get("/monthly/{month}")
def monthly_detail(month: str, _: Principal = Depends(require(Perm.VIEW_INSIGHTS)), db: Session = Depends(get_db)) -> dict:
    s = db.get(MonthlySummary, _month(month))
    if s is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No monthly report for that month yet.")
    return {"month": month, "label": monthly.label(month), "status": s.status, "summary": json.loads(s.summary),
            "items": [mail.item_dict(i) for i in monthly.items(db, month)]}


class ApproveIn(BaseModel):
    ids: list[int] | None = None


@router.post("/monthly/{month}/approve")
def monthly_approve(month: str, body: ApproveIn, principal: Principal = Depends(require(Perm.UPLOAD_AND_SEND)),
                    settings: Settings = Depends(get_settings), db: Session = Depends(get_db)) -> dict:
    todo = [i for i in monthly.items(db, _month(month)) if i.status in mail.SENDABLE and (body.ids is None or i.id in body.ids)]
    done = mail.send_items(db, settings, todo, principal.username)
    return {"sent_now": len(done), "items": [mail.item_dict(i) for i in monthly.items(db, month)]}


@router.get("/monthly/{month}/archive")
def monthly_archive(month: str, _: Principal = Depends(require(Perm.MANAGE_SETTINGS)), db: Session = Depends(get_db)) -> Response:
    s = db.get(MonthlySummary, _month(month))
    if s is None or not s.archive_path or not Path(s.archive_path).is_file():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No archive for that month.")
    return Response(Path(s.archive_path).read_bytes(), media_type=XLSX,
                    headers={"Content-Disposition": f'attachment; filename="attendance_archive_{month}.xlsx"'})


class CleanupIn(BaseModel):
    confirm: bool = False


@router.post("/monthly/{month}/cleanup")
def monthly_cleanup(month: str, body: CleanupIn, principal: Principal = Depends(require(Perm.MANAGE_SETTINGS)),
                    settings: Settings = Depends(get_settings), engine: Engine = Depends(get_engine)) -> dict:
    """confirm=false: show what would happen and why it is (not) allowed; confirm=true: do it if every check passes."""
    try:
        return monthly.cleanup(settings, engine, _month(month), body.confirm, trigger="MANUAL", actor=principal.username)
    except jobs.JobLocked as exc:
        raise _locked(exc) from None
