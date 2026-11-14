"""security.* tables (PRD 10.3)."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from core.timeutils import now_utc
from database.models.base import Base, UtcDateTime

SCHEMA = "security"


class AppUser(Base):
    __tablename__ = "app_user"
    __table_args__ = {"schema": SCHEMA}

    user_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    display_name: Mapped[str] = mapped_column(String(200), nullable=False)
    email: Mapped[str | None] = mapped_column(String(320))
    password_hash: Mapped[str | None] = mapped_column(String(100))  # null for future SSO users
    auth_provider: Mapped[str] = mapped_column(String(20), nullable=False, default="LOCAL")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    failed_login_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(UtcDateTime)
    last_login_at: Mapped[datetime | None] = mapped_column(UtcDateTime)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False, default=now_utc)
    updated_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False, default=now_utc, onupdate=now_utc)
    created_by: Mapped[str | None] = mapped_column(String(100))

    roles: Mapped[list["UserRole"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    departments: Mapped[list["UserDepartmentAccess"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )


class AppRole(Base):
    __tablename__ = "app_role"
    __table_args__ = {"schema": SCHEMA}

    role_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    role_code: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    description: Mapped[str | None] = mapped_column(String(500))

    permissions: Mapped[list["RolePermission"]] = relationship(back_populates="role", cascade="all, delete-orphan")


class Permission(Base):
    __tablename__ = "permission"
    __table_args__ = {"schema": SCHEMA}

    permission_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    permission_code: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    description: Mapped[str | None] = mapped_column(String(500))


class UserRole(Base):
    __tablename__ = "user_role"
    __table_args__ = {"schema": SCHEMA}

    user_id: Mapped[int] = mapped_column(ForeignKey(f"{SCHEMA}.app_user.user_id"), primary_key=True)
    role_id: Mapped[int] = mapped_column(ForeignKey(f"{SCHEMA}.app_role.role_id"), primary_key=True)
    granted_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False, default=now_utc)
    granted_by: Mapped[str | None] = mapped_column(String(100))

    user: Mapped[AppUser] = relationship(back_populates="roles")
    role: Mapped[AppRole] = relationship()


class RolePermission(Base):
    __tablename__ = "role_permission"
    __table_args__ = {"schema": SCHEMA}

    role_id: Mapped[int] = mapped_column(ForeignKey(f"{SCHEMA}.app_role.role_id"), primary_key=True)
    permission_id: Mapped[int] = mapped_column(ForeignKey(f"{SCHEMA}.permission.permission_id"), primary_key=True)

    role: Mapped[AppRole] = relationship(back_populates="permissions")
    permission: Mapped[Permission] = relationship()


class UserDepartmentAccess(Base):
    """Explicit department scope (e.g. for HODs). department_code will gain an FK to
    hr.dim_department once the department master exists (Phase 4/7)."""

    __tablename__ = "user_department_access"
    __table_args__ = {"schema": SCHEMA}

    user_id: Mapped[int] = mapped_column(ForeignKey(f"{SCHEMA}.app_user.user_id"), primary_key=True)
    department_code: Mapped[str] = mapped_column(String(50), primary_key=True)
    granted_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False, default=now_utc)
    granted_by: Mapped[str | None] = mapped_column(String(100))

    user: Mapped[AppUser] = relationship(back_populates="departments")
