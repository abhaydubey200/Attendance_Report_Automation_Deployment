"""Signed, short-lived session tokens carried in an httpOnly cookie.

The token only identifies the user; effective permissions are reloaded from the
database on every request, so deactivation and role changes apply immediately.
Expiry slides on each authenticated request (idle timeout).
"""

from __future__ import annotations

import logging
import secrets
from datetime import timedelta

import jwt
from fastapi import Response

from core.config import Settings
from core.timeutils import now_utc

log = logging.getLogger(__name__)

_ALGORITHM = "HS256"
_TOKEN_TYPE = "apis-mis-session"


def resolve_secret(settings: Settings) -> str:
    """APP_SECRET_KEY, or an ephemeral key outside production (sessions end on restart)."""
    if settings.api.secret_key:
        return settings.api.secret_key.get_secret_value()
    log.warning("APP_SECRET_KEY not set; using an ephemeral session key (development/testing only)")
    return secrets.token_urlsafe(48)


def issue_token(user_id: int, secret: str, idle_minutes: int) -> str:
    now = now_utc()
    claims = {"sub": str(user_id), "typ": _TOKEN_TYPE, "iat": now, "exp": now + timedelta(minutes=idle_minutes)}
    return jwt.encode(claims, secret, algorithm=_ALGORITHM)


def read_token(token: str, secret: str) -> int | None:
    try:
        claims = jwt.decode(token, secret, algorithms=[_ALGORITHM], options={"require": ["exp", "sub", "typ"]})
    except jwt.PyJWTError:
        return None
    if claims.get("typ") != _TOKEN_TYPE:
        return None
    try:
        return int(claims["sub"])
    except (TypeError, ValueError):
        return None


def set_session_cookie(response: Response, settings: Settings, token: str) -> None:
    response.set_cookie(
        settings.api.cookie_name,
        token,
        max_age=settings.session.idle_timeout_minutes * 60,
        httponly=True,
        secure=settings.api.cookie_secure,
        samesite="strict",
        path="/",
    )


def clear_session_cookie(response: Response, settings: Settings) -> None:
    response.delete_cookie(settings.api.cookie_name, path="/", secure=settings.api.cookie_secure, httponly=True, samesite="strict")
