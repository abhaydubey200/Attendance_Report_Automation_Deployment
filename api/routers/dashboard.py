"""Executive dashboard (PRD 4.4): KPIs come only from the current processing run of the
chosen date, scoped to the caller's departments."""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from api.deps import get_db, get_settings, require
from core.config import Settings, load_attendance_rules
from core.timeutils import today_ist
from reporting import analytics
from security.permissions import Perm, Principal

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("/summary")
def summary(day: date | None = Query(None, alias="date"), principal: Principal = Depends(require(Perm.DASHBOARD_VIEW)),
            settings: Settings = Depends(get_settings), db: Session = Depends(get_db)) -> dict:
    rules = load_attendance_rules(settings.config_dir)
    data = analytics.summary(db, principal, rules, day)
    return {
        "today_ist": today_ist().isoformat(),
        "rule_version": rules.rule_version,
        "rule_approval_status": rules.approval_status,
        "rules_approved": rules.is_approved,
        "message": None if data.get("run") else
        "No processed attendance yet. Upload datasets and start a processing run to see KPIs here.",
        **data,
    }
