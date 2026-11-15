from __future__ import annotations

import json
from datetime import timedelta

from sqlalchemy import select

from core.timeutils import now_utc
from database.connection import session_scope
from database.models.audit import UserActivityLog
from database.models.security import AppUser
from security.authentication import authenticate, hash_password, validate_password_policy, verify_password
from tests.conftest import TEST_PASSWORD


def _login(engine, settings, username, password):
    with session_scope(engine) as s:
        return authenticate(s, username, password, settings.session)


def _audit(engine):
    with session_scope(engine) as s:
        return [(r.action, r.outcome, r.username, r.detail) for r in s.scalars(select(UserActivityLog).order_by(UserActivityLog.activity_id))]


def test_hash_and_verify():
    h = hash_password("Correct-Horse-9")
    assert h != "Correct-Horse-9" and verify_password("Correct-Horse-9", h)
    assert not verify_password("wrong", h)
    assert not verify_password("anything", None)
    assert not verify_password("x" * 100, h)  # > 72 bytes never verifies


def test_password_policy():
    assert validate_password_policy("short", 12)
    assert validate_password_policy("alllowercaseletters", 12)
    assert validate_password_policy("Good-Password-1", 12) == []
    assert validate_password_policy("Aa1!" + "x" * 80, 12)  # bcrypt byte limit


def test_successful_login_returns_principal_and_audits(engine, settings, make_user):
    make_user("hr.admin", ["HR"])
    principal = _login(engine, settings, "  HR.Admin ", TEST_PASSWORD)
    assert principal is not None and principal.username == "hr.admin"
    assert "HR" in principal.roles and "UPLOAD_AND_SEND" in principal.permissions
    assert _audit(engine)[-1][:2] == ("LOGIN", "SUCCESS")


def test_wrong_password_and_unknown_user_fail_and_are_audited(engine, settings, make_user):
    make_user("user1", ["VIEWER"])
    assert _login(engine, settings, "user1", "bad") is None
    assert _login(engine, settings, "nobody", "bad") is None
    events = _audit(engine)
    assert [e[:2] for e in events] == [("LOGIN", "FAILED"), ("LOGIN", "FAILED")]
    # The attempted password is never stored.
    assert all("bad" not in (e[3] or "").replace("bad_password", "") for e in events)


def test_lockout_after_max_failures(engine, settings, make_user):
    make_user("user2", ["VIEWER"])
    for _ in range(settings.session.max_failed_logins):
        assert _login(engine, settings, "user2", "wrong") is None
    # Correct password is now refused while locked.
    assert _login(engine, settings, "user2", TEST_PASSWORD) is None
    assert _audit(engine)[-1][:2] == ("LOGIN", "DENIED")
    assert json.loads(_audit(engine)[-2][3])["locked"] is True

    # After the lockout window, login succeeds.
    with session_scope(engine) as s:
        user = s.scalar(select(AppUser).where(AppUser.username == "user2"))
        user.locked_until = now_utc() - timedelta(seconds=1)
    assert _login(engine, settings, "user2", TEST_PASSWORD) is not None


def test_inactive_user_cannot_log_in(engine, settings, make_user):
    make_user("leaver", ["VIEWER"], active=False)
    assert _login(engine, settings, "leaver", TEST_PASSWORD) is None
