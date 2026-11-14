"""Administration endpoints (read-only in Phase 1; users are created via CLI)."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from api.deps import get_db, get_settings, require
from api.schemas import RoleRow, UserRow
from core.config import Settings
from core.timeutils import ensure_utc
from database.repositories.security_repository import SecurityRepository
from security.permissions import Perm, Principal

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/users", response_model=list[UserRow])
def users(_: Principal = Depends(require(Perm.ADMIN_USERS)), db: Session = Depends(get_db)) -> list[UserRow]:
    return [
        UserRow(
            user_id=u.user_id,
            username=u.username,
            display_name=u.display_name,
            roles=sorted(r.role.role_code for r in u.roles),
            departments=sorted(d.department_code for d in u.departments),
            is_active=u.is_active,
            last_login_at=ensure_utc(u.last_login_at),
        )
        for u in SecurityRepository(db).list_users()
    ]


@router.get("/roles", response_model=list[RoleRow])
def roles(_: Principal = Depends(require(Perm.ADMIN_USERS)), settings: Settings = Depends(get_settings)) -> list[RoleRow]:
    return [
        RoleRow(role=name, description=d.description, permissions=list(d.permissions))
        for name, d in settings.security.roles.items()
    ]


@router.get("/settings")
def app_settings(_: Principal = Depends(require(Perm.ADMIN_SETTINGS)), settings: Settings = Depends(get_settings)) -> dict:
    """Read-only operational settings. Changes go through config files + review (PRD 22)."""
    from core.config import load_recipients

    recipients = load_recipients(settings.config_dir)
    return {
        "environment": settings.environment,
        "auth_mode": settings.auth.mode,
        "email": {"enabled": settings.features.email_enabled, "transport": settings.email.transport,
                  "sender": settings.email.sender, "test_recipients": list(settings.email.test_recipients),
                  "recipients_approval": recipients.get("approval_status"),
                  "hod_lists": len(recipients.get("hod_reports") or {}),
                  "directors": len(recipients.get("directors_reports") or []),
                  "hr": len(recipients.get("hr_operational") or [])},
        "ai": {"enabled": settings.features.ai_enabled, "provider": settings.ai.provider, "model": settings.ai.model,
               "endpoint_configured": bool(settings.ai.endpoint), "timeout_seconds": settings.ai.timeout_seconds},
        "uploads": {"max_file_size_mb": settings.uploads.max_file_size_mb, "allowed_extensions": list(settings.uploads.allowed_extensions)},
        "session": {"idle_timeout_minutes": settings.session.idle_timeout_minutes,
                    "max_failed_logins": settings.session.max_failed_logins},
    }


@router.get("/rules")
def rules(_: Principal = Depends(require(Perm.ADMIN_RULES)), settings: Settings = Depends(get_settings)) -> dict:
    from core.config import load_attendance_rules, load_source_authority

    r = load_attendance_rules(settings.config_dir)
    a = load_source_authority(settings.config_dir)
    return {"rule_version": r.rule_version, "approval_status": r.approval_status, "approved_by": r.approved_by,
            "approved_on": r.approved_on, "is_approved": r.is_approved,
            "calculation": {k: v for k, v in r.calculation.model_dump().items()},
            "unresolved": r.calculation.unresolved_rules(),
            "source_authority": {"approval_status": a.approval_status,
                                 "domains": {k: v.model_dump() for k, v in a.domains.items()}}}


@router.get("/audit")
def audit(limit: int = 200, _: Principal = Depends(require(Perm.AUDIT_VIEW)), db: Session = Depends(get_db)) -> list[dict]:
    from sqlalchemy import select

    from database.models.audit import UserActivityLog

    rows = db.scalars(select(UserActivityLog).order_by(UserActivityLog.activity_id.desc()).limit(min(max(limit, 1), 1000)))
    return [{"at": ensure_utc(r.occurred_at).isoformat(), "username": r.username, "action": r.action, "outcome": r.outcome,
             "detail": r.detail} for r in rows]
