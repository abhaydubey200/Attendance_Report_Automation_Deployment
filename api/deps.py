"""FastAPI dependencies: settings, DB session, authenticated principal, permission guards."""

from __future__ import annotations

from typing import Callable, Iterator

from fastapi import Depends, HTTPException, Request, Response, status
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from api.sessions import issue_token, read_token, set_session_cookie
from core.config import Settings
from database.connection import session_scope
from database.repositories.security_repository import SecurityRepository
from security.authorization import require_permission
from security.permissions import Perm, Principal


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_engine(request: Request) -> Engine:
    return request.app.state.engine


def get_db(engine: Engine = Depends(get_engine)) -> Iterator[Session]:
    with session_scope(engine) as session:
        yield session


def current_principal(
    request: Request,
    response: Response,
    settings: Settings = Depends(get_settings),
    db: Session = Depends(get_db),
) -> Principal:
    token = request.cookies.get(settings.api.cookie_name)
    secret: str = request.app.state.session_secret
    user_id = read_token(token, secret) if token else None
    principal = SecurityRepository(db).load_principal(user_id) if user_id is not None else None
    if principal is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated")
    # Sliding idle timeout.
    set_session_cookie(response, settings, issue_token(principal.user_id, secret, settings.session.idle_timeout_minutes))
    return principal


def require(perm: Perm) -> Callable[..., Principal]:
    """Route dependency: authenticated AND holding `perm` (AuthorizationError -> 403)."""

    def _guard(principal: Principal = Depends(current_principal)) -> Principal:
        require_permission(principal, perm)
        return principal

    return _guard
