"""Server-side authorization checks (PRD 3.6).

Every data retrieval and report download must call these functions; hiding UI
navigation is never sufficient on its own.
"""

from __future__ import annotations

from typing import Iterable

from core.exceptions import AuthorizationError
from security.permissions import Perm, Principal


def has_permission(principal: Principal | None, perm: Perm | str) -> bool:
    return principal is not None and str(perm) in principal.permissions


def require_permission(principal: Principal | None, perm: Perm | str) -> None:
    if not has_permission(principal, perm):
        raise AuthorizationError(f"missing permission {perm}")


def has_all_departments(principal: Principal | None) -> bool:
    return has_permission(principal, Perm.ATTENDANCE_VIEW_ALL_DEPARTMENTS)


def can_access_department(principal: Principal | None, department_code: str) -> bool:
    if principal is None:
        return False
    return has_all_departments(principal) or department_code in principal.departments


def require_department_access(principal: Principal | None, department_code: str) -> None:
    if not can_access_department(principal, department_code):
        raise AuthorizationError(f"no access to department {department_code}")


def can_view_employee_records(principal: Principal | None, department_code: str) -> bool:
    """Employee-level data needs BOTH the employee permission and department scope."""
    return has_permission(principal, Perm.ATTENDANCE_VIEW_EMPLOYEE) and can_access_department(
        principal, department_code
    )


def scope_departments(principal: Principal | None, departments: Iterable[str]) -> list[str]:
    """Filter a department list down to what the principal may see."""
    return [d for d in departments if can_access_department(principal, d)]
