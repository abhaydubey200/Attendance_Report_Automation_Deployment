"""Login page."""

from __future__ import annotations

import streamlit as st

from database.connection import session_scope
from security.authentication import GENERIC_FAILURE, authenticate
from ui.context import app_engine, app_settings, sign_in
from ui.theme import page_header


def render_login() -> None:
    settings = app_settings()
    _, center, _ = st.columns([1, 1.2, 1])
    with center:
        page_header(settings.app.name, "Sign in to continue")
        notice = st.session_state.pop("auth_notice", None)
        if notice:
            st.info(notice)
        with st.form("login", clear_on_submit=True):
            username = st.text_input("Username", key="login_username")
            password = st.text_input("Password", type="password", key="login_password")
            submitted = st.form_submit_button("Sign in", type="primary", width="stretch")
        if submitted:
            with session_scope(app_engine()) as session:
                principal = authenticate(session, username, password, settings.session)
            if principal is None:
                st.error(GENERIC_FAILURE)
            else:
                sign_in(principal)
                st.rerun()
        st.caption(f"Environment: {settings.environment}")
