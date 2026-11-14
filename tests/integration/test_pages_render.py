"""Every registered page renders for an authorised principal and refuses an unauthorised one."""

from __future__ import annotations

import pytest
from streamlit.testing.v1 import AppTest

from ui.navigation import PAGES

SCRIPT = """
from security.permissions import Perm, Principal
from ui.navigation import PAGES, _placeholder
from core.exceptions import AuthorizationError
import streamlit as st

perms = frozenset(p.value for p in Perm) if {allowed} else frozenset()
principal = Principal(1, "tester", "Tester", permissions=perms)
spec = next(s for s in PAGES if s.slug == "{slug}")
try:
    (spec.renderer or _placeholder(spec))(principal)
except AuthorizationError:
    st.error("DENIED")
"""


@pytest.fixture
def fresh_resources():
    import streamlit as st

    st.cache_resource.clear()
    yield
    st.cache_resource.clear()


@pytest.mark.parametrize("slug", [p.slug for p in PAGES])
def test_page_renders_when_authorised(engine, fresh_resources, slug):
    at = AppTest.from_string(SCRIPT.format(slug=slug, allowed=True), default_timeout=30).run()
    assert not at.exception, at.exception
    assert not any(e.value == "DENIED" for e in at.error)


@pytest.mark.parametrize("slug", [p.slug for p in PAGES])
def test_page_refuses_when_unauthorised(engine, fresh_resources, slug):
    at = AppTest.from_string(SCRIPT.format(slug=slug, allowed=False), default_timeout=30).run()
    assert not at.exception
    assert [e.value for e in at.error] == ["DENIED"]
    # Nothing but the denial is rendered.
    assert not at.dataframe and not at.metric
