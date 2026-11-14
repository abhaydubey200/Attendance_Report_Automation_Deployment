"""Permission and role vocabulary. The authoritative assignments live in the
security.* tables (seeded from config/security.yaml)."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class Role(StrEnum):
    SYSTEM_ADMIN = "SYSTEM_ADMIN"
    HR_ADMIN = "HR_ADMIN"
    HR_MANAGER = "HR_MANAGER"
    HOD = "HOD"
    DIRECTOR = "DIRECTOR"
    READ_ONLY = "READ_ONLY"


class Perm(StrEnum):
    DASHBOARD_VIEW = "DASHBOARD_VIEW"
    DATA_UPLOAD = "DATA_UPLOAD"
    DATA_REGISTRY_VIEW = "DATA_REGISTRY_VIEW"
    DATA_REGISTRY_MANAGE = "DATA_REGISTRY_MANAGE"
    DATA_QUALITY_VIEW = "DATA_QUALITY_VIEW"
    ATTENDANCE_VIEW_AGGREGATE = "ATTENDANCE_VIEW_AGGREGATE"
    ATTENDANCE_VIEW_EMPLOYEE = "ATTENDANCE_VIEW_EMPLOYEE"
    ATTENDANCE_VIEW_ALL_DEPARTMENTS = "ATTENDANCE_VIEW_ALL_DEPARTMENTS"
    RECONCILIATION_VIEW = "RECONCILIATION_VIEW"
    RECONCILIATION_RESOLVE = "RECONCILIATION_RESOLVE"
    REPORT_VIEW_HOD = "REPORT_VIEW_HOD"
    REPORT_VIEW_DIRECTORS = "REPORT_VIEW_DIRECTORS"
    REPORT_GENERATE = "REPORT_GENERATE"
    REPORT_APPROVE = "REPORT_APPROVE"
    AI_USE = "AI_USE"
    ADMIN_USERS = "ADMIN_USERS"
    ADMIN_MAPPING = "ADMIN_MAPPING"
    ADMIN_RULES = "ADMIN_RULES"
    ADMIN_SETTINGS = "ADMIN_SETTINGS"
    SYSTEM_MONITOR = "SYSTEM_MONITOR"
    AUDIT_VIEW = "AUDIT_VIEW"


@dataclass(frozen=True)
class Principal:
    """An authenticated user's effective rights, loaded fresh from the database."""

    user_id: int
    username: str
    display_name: str
    roles: frozenset[str] = field(default_factory=frozenset)
    permissions: frozenset[str] = field(default_factory=frozenset)
    departments: frozenset[str] = field(default_factory=frozenset)
