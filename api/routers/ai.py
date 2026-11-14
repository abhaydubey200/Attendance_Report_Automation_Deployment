"""AI intelligence API (PRD 14-15). Optional; never changes official values."""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ai_engine import analyst
from ai_engine.summary_generator import generate_run_summary
from api.deps import get_db, get_settings, require
from core.config import Settings
from database.models.reporting import AISummary
from reporting import analytics
from security.authorization import has_all_departments
from security.permissions import Perm, Principal

router = APIRouter(prefix="/ai", tags=["ai"])


@router.get("/status")
def ai_status(_: Principal = Depends(require(Perm.AI_USE)), settings: Settings = Depends(get_settings)) -> dict:
    return {"enabled": settings.features.ai_enabled, "model": settings.ai.model if settings.features.ai_enabled else None,
            "provider": settings.ai.provider}


@router.get("/summary")
def summary(day: date | None = Query(None, alias="date"), principal: Principal = Depends(require(Perm.AI_USE)),
            db: Session = Depends(get_db)) -> dict:
    run = analytics.current_run(db, day)
    if run is None:
        return {"run": None, "summary": None}
    if not has_all_departments(principal):   # organisation commentary is organisation-level data
        return {"run": analytics.run_info(run), "summary": None, "note": "Organisation summary needs organisation-level access."}
    s = db.scalar(select(AISummary).where(AISummary.run_id == run.run_id, AISummary.scope == "ORG").order_by(AISummary.id.desc()))
    return {"run": analytics.run_info(run),
            "summary": {"status": s.status, "text": s.summary, "model": s.model, "prompt_version": s.prompt_version,
                        "created_at": s.created_at.isoformat()} if s else None}


@router.post("/summary/{run_id}")
def regenerate(run_id: int, _: Principal = Depends(require(Perm.REPORT_GENERATE)), settings: Settings = Depends(get_settings),
               db: Session = Depends(get_db)) -> dict:
    return {"generated": generate_run_summary(db, settings, run_id)}


class AskIn(BaseModel):
    question: str = Field(min_length=2, max_length=300)


@router.post("/ask")
def ask(body: AskIn, principal: Principal = Depends(require(Perm.AI_USE)), settings: Settings = Depends(get_settings),
        db: Session = Depends(get_db)) -> dict:
    try:
        return analyst.ask(db, settings, principal, body.question)
    except LookupError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found") from None
