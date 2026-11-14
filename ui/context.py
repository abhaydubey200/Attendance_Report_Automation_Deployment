"""Per-process resources and per-session principal handling for the Streamlit app."""

from __future__ import annotations

import streamlit as st
from sqlalchemy import Engine

from core.config import Settings, get_settings
from core.logging_setup import configure_logging
from core.timeutils import now_utc
from database.connection import create_db_engine, session_scope
from database.repositories.security_repository import SecurityRepository
from security.audit import record_activity
from security.permissions import Principal

_USER_KEY = "auth_user_id"
_ACTIVITY_KEY = "auth_last_activity"


@st.cache_resource(show_spinner=False)
def app_settings() -> Settings:
    settings = get_settings()
    configure_logging(settings)
    return settings


@st.cache_resource(show_spinner=False)
def app_engine() -> Engine:
    return create_db_engine(app_settings())


def sign_in(principal: Principal) -> None:
    st.session_state[_USER_KEY] = principal.user_id
    st.session_state[_ACTIVITY_KEY] = now_utc()


def sign_out(reason: str = "LOGOUT") -> None:
    user_id = st.session_state.get(_USER_KEY)
    if user_id is not None:
        with session_scope(app_engine()) as session:
            record_activity(session, reason, "SUCCESS", user_id=user_id)
    for key in (_USER_KEY, _ACTIVITY_KEY):
        st.session_state.pop(key, None)


def current_principal() -> Principal | None:
    """Reload the principal from the database on every run so role changes and
    deactivations take effect immediately. Enforces the idle timeout."""
    user_id = st.session_state.get(_USER_KEY)
    if user_id is None:
        return None

    settings = app_settings()
    last = st.session_state.get(_ACTIVITY_KEY)
    if last and (now_utc() - last).total_seconds() > settings.session.idle_timeout_minutes * 60:
        sign_out("SESSION_TIMEOUT")
        st.session_state["auth_notice"] = "Your session expired due to inactivity. Please sign in again."
        return None

    with session_scope(app_engine()) as session:
        principal = SecurityRepository(session).load_principal(user_id)
    if principal is None:
        sign_out("SESSION_REVOKED")
        return None
    st.session_state[_ACTIVITY_KEY] = now_utc()
    return principal
