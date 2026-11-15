"""Server-side permission checks. Every API route declares the permission it needs."""

from __future__ import annotations

from core.exceptions import AuthorizationError
from security.permissions import Perm, Principal


def has_permission(principal: Principal | None, perm: Perm | str) -> bool:
    return principal is not None and str(perm) in principal.permissions


def require_permission(principal: Principal | None, perm: Perm | str) -> None:
    if not has_permission(principal, perm):
        raise AuthorizationError(f"missing permission {perm}")
