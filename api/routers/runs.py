"""Processing runs: start, resume, approve, distribute, inspect (PRD 17, 19)."""

from __future__ import annotations

import json
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from api.deps import current_principal, get_db, get_engine, get_settings, require
from core.config import Settings
from core.exceptions import AuthorizationError
from database.models.attendance import ProcessingRun
from database.models.audit import ProcessingLog
from email_engine.distribution_manager import DistributionError, distribute
from orchestration.pipeline import PipelineError, approve_run, resume_run, start_run
from security.authorization import has_permission
from security.permissions import Perm, Principal

router = APIRouter(prefix="/runs", tags=["processing"])


def _viewer(principal: Principal = Depends(current_principal)) -> Principal:
    if not (has_permission(principal, Perm.SYSTEM_MONITOR) or has_permission(principal, Perm.REPORT_GENERATE)):
        raise AuthorizationError("runs not permitted")
    return principal


def _row(r: ProcessingRun) -> dict:
    return {"run_id": r.run_id, "run_ref": r.run_ref, "reporting_date": r.reporting_date.isoformat(), "version_no": r.version_no,
            "state": r.state, "is_current": r.is_current, "rule_version": r.rule_version, "rules_approved": r.rules_approved,
            "ai_status": r.ai_status, "error": r.error, "started_by": r.started_by, "started_at": r.started_at.isoformat(),
            "finished_at": r.finished_at.isoformat() if r.finished_at else None, "approved_by": r.approved_by,
            "approved_at": r.approved_at.isoformat() if r.approved_at else None}


@router.get("")
def list_runs(_: Principal = Depends(_viewer), db: Session = Depends(get_db)) -> list[dict]:
    return [_row(r) for r in db.scalars(select(ProcessingRun).order_by(ProcessingRun.run_id.desc()).limit(200))]


@router.get("/{run_id}")
def run_detail(run_id: int, _: Principal = Depends(_viewer), db: Session = Depends(get_db)) -> dict:
    r = db.get(ProcessingRun, run_id)
    if r is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Run not found")
    logs = [{"stage": l.stage, "outcome": l.outcome, "started_at": l.started_at.isoformat(), "duration_ms": l.duration_ms,
             "record_count": l.record_count, "message": l.message}
            for l in db.scalars(select(ProcessingLog).where(ProcessingLog.run_id == run_id).order_by(ProcessingLog.id))]
    return {**_row(r), "stats": json.loads(r.stats or "{}"), "inputs": json.loads(r.inputs), "logs": logs}


class StartIn(BaseModel):
    reporting_date: date


@router.post("")
def start(body: StartIn, principal: Principal = Depends(require(Perm.REPORT_GENERATE)), engine: Engine = Depends(get_engine),
          settings: Settings = Depends(get_settings)) -> dict:
    try:
        res = start_run(engine, settings, body.reporting_date, principal.username)
    except PipelineError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from None
    return {"run_id": res.run_id, "run_ref": res.run_ref, "state": res.state, "created": res.created}


@router.post("/{run_id}/resume")
def resume(run_id: int, principal: Principal = Depends(require(Perm.REPORT_GENERATE)), engine: Engine = Depends(get_engine),
           settings: Settings = Depends(get_settings)) -> dict:
    try:
        res = resume_run(engine, settings, run_id, principal.username)
    except PipelineError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from None
    return {"run_id": res.run_id, "run_ref": res.run_ref, "state": res.state}


@router.post("/{run_id}/approve")
def approve(run_id: int, principal: Principal = Depends(require(Perm.REPORT_APPROVE)), engine: Engine = Depends(get_engine)) -> dict:
    try:
        return {"state": approve_run(engine, run_id, principal.username)}
    except Exception as exc:  # invalid transition or missing run
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from None


@router.post("/{run_id}/distribute")
def distribute_reports(run_id: int, principal: Principal = Depends(require(Perm.REPORT_APPROVE)),
                       settings: Settings = Depends(get_settings), db: Session = Depends(get_db)) -> dict:
    try:
        r = distribute(db, settings, run_id, principal.username)
    except DistributionError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from None
    return {"mode": r.mode, "sent": r.sent, "failed": r.failed, "skipped_duplicates": r.skipped_duplicates, "problems": r.problems}
