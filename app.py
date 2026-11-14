"""Streamlit entry point:  streamlit run app.py   (or: python main.py run)"""

from __future__ import annotations

import logging

import streamlit as st

from core.exceptions import AuthorizationError, ConfigurationError
from database.connection import check_database
from ui.context import app_engine, app_settings, current_principal, sign_out
from ui.theme import apply_theme

log = logging.getLogger("app")

st.set_page_config(page_title="APIS Attendance MIS", page_icon=":material/fact_check:", layout="wide")
apply_theme()

try:
    settings = app_settings()
    engine = app_engine()
except ConfigurationError as exc:
    st.error(f"Configuration error: {exc}")
    st.stop()

db = check_database(engine, settings)
if not db.reachable or not db.schema_revision:
    st.error(f"Database not ready: {db.detail}. An administrator must run `python main.py init-db`.")
    st.stop()

principal = current_principal()
if principal is None:
    from ui.authentication import render_login

    render_login()
    st.stop()

from ui.navigation import build_navigation  # noqa: E402  (after auth gate)

with st.sidebar:
    st.markdown(f"**{settings.app.short_name}**")
    st.caption(f"{principal.display_name} · {', '.join(sorted(principal.roles)) or 'no role'}")
    if settings.environment != "production":
        st.caption(f":orange[{settings.environment.upper()} ENVIRONMENT]")
    if st.button("Sign out", width="stretch"):
        sign_out()
        st.rerun()

nav = st.navigation(build_navigation(principal))
try:
    nav.run()
except AuthorizationError:
    log.warning("authorization denied", extra={"page": nav.title, "audit_user_id": principal.user_id})
    st.error("You are not authorised to view this page.")
