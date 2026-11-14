"""Users, roles and permissions."""

from __future__ import annotations

from sqlalchemy import delete, select
from sqlalchemy.orm import Session, selectinload

from core.config import SecurityConfig
from database.models.security import (
    AppRole,
    AppUser,
    Permission,
    RolePermission,
    UserDepartmentAccess,
    UserRole,
)
from security.permissions import Principal


def normalise_username(username: str) -> str:
    return username.strip().lower()


class SecurityRepository:
    def __init__(self, session: Session) -> None:
        self.s = session

    # ------------------------------------------------------------------ roles / permissions
    def sync_roles_and_permissions(self, config: SecurityConfig) -> dict[str, int]:
        """Make the DB role->permission mapping match security.yaml exactly.
        Roles/permissions no longer in the config lose their grants but are not deleted
        (user assignments and history stay intact)."""
        perms = {p.permission_code: p for p in self.s.scalars(select(Permission))}
        for code, description in config.permissions.items():
            if code in perms:
                perms[code].description = description
            else:
                perms[code] = Permission(permission_code=code, description=description)
                self.s.add(perms[code])

        roles = {r.role_code: r for r in self.s.scalars(select(AppRole))}
        for code, definition in config.roles.items():
            if code in roles:
                roles[code].description = definition.description
            else:
                roles[code] = AppRole(role_code=code, description=definition.description)
                self.s.add(roles[code])
        self.s.flush()

        self.s.execute(delete(RolePermission))
        grants = 0
        for code, definition in config.roles.items():
            for perm_code in definition.permissions:
                self.s.add(RolePermission(role_id=roles[code].role_id, permission_id=perms[perm_code].permission_id))
                grants += 1
        self.s.flush()
        return {"permissions": len(config.permissions), "roles": len(config.roles), "grants": grants}

    # ------------------------------------------------------------------ users
    def get_user_by_username(self, username: str) -> AppUser | None:
        return self.s.scalar(select(AppUser).where(AppUser.username == normalise_username(username)))

    def get_user(self, user_id: int) -> AppUser | None:
        return self.s.get(AppUser, user_id)

    def list_users(self) -> list[AppUser]:
        stmt = (
            select(AppUser)
            .options(selectinload(AppUser.roles).selectinload(UserRole.role), selectinload(AppUser.departments))
            .order_by(AppUser.username)
        )
        return list(self.s.scalars(stmt))

    def create_user(
        self,
        username: str,
        display_name: str,
        password_hash: str | None,
        roles: list[str],
        departments: list[str] | None = None,
        email: str | None = None,
        created_by: str | None = None,
    ) -> AppUser:
        uname = normalise_username(username)
        if not uname:
            raise ValueError("username is required")
        if self.get_user_by_username(uname):
            raise ValueError(f"user {uname!r} already exists")
        role_rows = {r.role_code: r for r in self.s.scalars(select(AppRole).where(AppRole.role_code.in_(roles)))}
        missing = set(roles) - set(role_rows)
        if missing:
            raise ValueError(f"unknown roles (run init-db first?): {sorted(missing)}")
        user = AppUser(
            username=uname,
            display_name=display_name.strip() or uname,
            email=email,
            password_hash=password_hash,
            auth_provider="LOCAL",
            is_active=True,
            failed_login_count=0,
            created_by=created_by,
        )
        user.roles = [UserRole(role=role_rows[r], granted_by=created_by) for r in roles]
        user.departments = [
            UserDepartmentAccess(department_code=d.strip().upper(), granted_by=created_by)
            for d in sorted(set(departments or []))
            if d.strip()
        ]
        self.s.add(user)
        self.s.flush()
        return user

    def permissions_for_roles(self, role_codes: list[str] | tuple[str, ...]) -> frozenset[str]:
        rows = self.s.scalars(
            select(Permission.permission_code)
            .join(RolePermission, RolePermission.permission_id == Permission.permission_id)
            .join(AppRole, AppRole.role_id == RolePermission.role_id)
            .where(AppRole.role_code.in_(list(role_codes)))
        )
        return frozenset(rows)

    def load_principal(self, user_id: int) -> Principal | None:
        """Effective rights for an ACTIVE user, or None. Called on every request."""
        user = self.s.get(AppUser, user_id)
        if user is None or not user.is_active:
            return None
        role_ids = select(UserRole.role_id).where(UserRole.user_id == user_id)
        role_codes = self.s.scalars(select(AppRole.role_code).where(AppRole.role_id.in_(role_ids))).all()
        perm_codes = self.s.scalars(
            select(Permission.permission_code)
            .join(RolePermission, RolePermission.permission_id == Permission.permission_id)
            .where(RolePermission.role_id.in_(role_ids))
        ).all()
        depts = self.s.scalars(
            select(UserDepartmentAccess.department_code).where(UserDepartmentAccess.user_id == user_id)
        ).all()
        return Principal(
            user_id=user.user_id,
            username=user.username,
            display_name=user.display_name,
            roles=frozenset(role_codes),
            permissions=frozenset(perm_codes),
            departments=frozenset(depts),
        )
