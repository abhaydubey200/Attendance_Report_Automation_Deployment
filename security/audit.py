"""User activity audit trail (audit.user_activity_log)."""

from __future__ import annotations

import json
import logging
from typing import Any

from sqlalchemy.orm import Session

from core.logging_setup import redact_value
from database.models.audit import UserActivityLog

log = logging.getLogger("audit")


def record_activity(
    session: Session,
    action: str,
    outcome: str,
    *,
    user_id: int | None = None,
    username: str | None = None,
    detail: dict[str, Any] | None = None,
) -> None:
    safe_detail = redact_value("detail", detail) if detail else None
    session.add(
        UserActivityLog(
            user_id=user_id,
            username=username,
            action=action,
            outcome=outcome,
            detail=json.dumps(safe_detail, default=str) if safe_detail else None,
        )
    )
    log.info("user activity", extra={"action": action, "outcome": outcome, "audit_user_id": user_id})
