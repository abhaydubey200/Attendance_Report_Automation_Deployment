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
