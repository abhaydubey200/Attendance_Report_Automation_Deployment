"""Authentication endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy.orm import Session

from api.deps import current_principal, get_db, get_settings
from api.navigation import visible_pages
from api.schemas import LoginRequest, Me, NavPage
from api.sessions import clear_session_cookie, issue_token, read_token, set_session_cookie
from core.config import Settings
from security.audit import record_activity
from security.authentication import GENERIC_FAILURE, authenticate
from security.permissions import Principal

router = APIRouter(prefix="/auth", tags=["auth"])


def _me(principal: Principal, settings: Settings) -> Me:
    return Me(
        user_id=principal.user_id,
        username=principal.username,
        display_name=principal.display_name,
        roles=sorted(principal.roles),
        permissions=sorted(principal.permissions),
        departments=sorted(principal.departments),
        navigation=[
            NavPage(section=p.section, title=p.title, slug=p.slug, implemented=p.implemented, phase=p.phase)
            for p in visible_pages(principal)
        ],
        environment=settings.environment,
        app_name=settings.app.name,
        idle_timeout_minutes=settings.session.idle_timeout_minutes,
    )


@router.post("/login", response_model=Me)
def login(
    body: LoginRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> Me:
    principal = authenticate(db, body.username, body.password, settings.session)
    if principal is None:
        # Commit the failed-attempt counter and audit row before responding.
        db.commit()
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, GENERIC_FAILURE)
    token = issue_token(principal.user_id, request.app.state.session_secret, settings.session.idle_timeout_minutes)
    set_session_cookie(response, settings, token)
    return _me(principal, settings)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> Response:
    # Deliberately not using current_principal: that would re-issue the cookie.
    token = request.cookies.get(settings.api.cookie_name)
    user_id = read_token(token, request.app.state.session_secret) if token else None
    if user_id is not None:
        record_activity(db, "LOGOUT", "SUCCESS", user_id=user_id)
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    clear_session_cookie(response, settings)
    return response


@router.get("/me", response_model=Me)
def me(principal: Principal = Depends(current_principal), settings: Settings = Depends(get_settings)) -> Me:
    return _me(principal, settings)
