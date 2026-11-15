"""Permission and role vocabulary (assignments live in the security.* tables)."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class Role(StrEnum):
    ADMIN = "ADMIN"
    HR = "HR"
    VIEWER = "VIEWER"


class Perm(StrEnum):
    VIEW_INSIGHTS = "VIEW_INSIGHTS"
    UPLOAD_AND_SEND = "UPLOAD_AND_SEND"
    MANAGE_SETTINGS = "MANAGE_SETTINGS"
    MANAGE_EMPLOYEES = "MANAGE_EMPLOYEES"
    ADMIN_USERS = "ADMIN_USERS"


@dataclass(frozen=True)
class Principal:
    """An authenticated user's effective rights, loaded fresh from the database."""

    user_id: int
    username: str
    display_name: str
    roles: frozenset[str] = field(default_factory=frozenset)
    permissions: frozenset[str] = field(default_factory=frozenset)
    departments: frozenset[str] = field(default_factory=frozenset)
