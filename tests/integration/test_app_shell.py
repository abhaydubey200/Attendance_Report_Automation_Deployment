"""Streamlit shell smoke tests using streamlit.testing (no browser)."""

from __future__ import annotations

import pytest
from streamlit.testing.v1 import AppTest

from core.paths import PROJECT_ROOT
from security.permissions import Perm, Principal
from tests.conftest import TEST_PASSWORD
from ui.navigation import PAGES, visible_pages

APP = str(PROJECT_ROOT / "app.py")


@pytest.fixture
def clear_streamlit_caches():
    import streamlit as st

    st.cache_resource.clear()
    yield
    st.cache_resource.clear()


def _login(at: AppTest, username: str, password: str) -> AppTest:
    at.text_input(key="login_username").input(username)
    at.text_input(key="login_password").input(password)
    at.button[0].click()
    return at.run()


def test_uninitialised_database_blocks_app(isolated_env, clear_streamlit_caches):
    at = AppTest.from_file(APP, default_timeout=30).run()
    assert not at.exception
    assert any("init-db" in e.value for e in at.error)


def test_login_gate_and_successful_login(engine, make_user, clear_streamlit_caches):
    make_user("hr.manager", ["HR_MANAGER"])
    at = AppTest.from_file(APP, default_timeout=30).run()
    assert not at.exception
    assert at.text_input(key="login_password")  # login form shown, nothing else

    at = _login(at, "hr.manager", "wrong-password")
    assert any("Invalid username or password" in e.value for e in at.error)
    assert "auth_user_id" not in at.session_state

    at = _login(at, "hr.manager", TEST_PASSWORD)
    assert not at.exception
    assert at.session_state["auth_user_id"]
    assert any("Executive Dashboard" in m.value for m in at.markdown)


def test_system_admin_lands_on_permitted_page(engine, make_user, clear_streamlit_caches):
    make_user("sys", ["SYSTEM_ADMIN"])
    at = AppTest.from_file(APP, default_timeout=30).run()
    at = _login(at, "sys", TEST_PASSWORD)
    assert not at.exception
    assert not any("Executive Dashboard" in m.value for m in at.markdown)


def _p(*perms: Perm) -> Principal:
    return Principal(1, "u", "U", permissions=frozenset(p.value for p in perms))


def test_navigation_is_permission_filtered():
    hod_pages = {p.slug for p in visible_pages(_p(Perm.DASHBOARD_VIEW, Perm.REPORT_VIEW_HOD))}
    assert "hod-reports" in hod_pages and "directors-reports" not in hod_pages and "users" not in hod_pages
    assert visible_pages(_p()) == []


def test_every_page_declares_a_permission_and_unique_slug():
    slugs = [p.slug for p in PAGES]
    assert len(slugs) == len(set(slugs))
    assert all(isinstance(p.permission, Perm) for p in PAGES)
    assert all(p.renderer or p.phase for p in PAGES)
