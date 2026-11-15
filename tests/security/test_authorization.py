from __future__ import annotations

import pytest

from core.exceptions import AuthorizationError
from database.connection import session_scope
from database.repositories.security_repository import SecurityRepository
from security.authorization import has_permission, require_permission
from security.permissions import Perm


def _principal(engine, user_id):
    with session_scope(engine) as s:
        return SecurityRepository(s).load_principal(user_id)


def test_roles_grant_the_expected_permissions(engine, make_user):
    admin = _principal(engine, make_user("boss", ["ADMIN"]))
    hr = _principal(engine, make_user("hr", ["HR"]))
    viewer = _principal(engine, make_user("view", ["VIEWER"]))
    assert {Perm.MANAGE_SETTINGS, Perm.UPLOAD_AND_SEND, Perm.VIEW_INSIGHTS} <= {Perm(p) for p in admin.permissions}
    assert has_permission(hr, Perm.UPLOAD_AND_SEND) and not has_permission(hr, Perm.MANAGE_SETTINGS)
    assert has_permission(viewer, Perm.VIEW_INSIGHTS)
    with pytest.raises(AuthorizationError):
        require_permission(viewer, Perm.UPLOAD_AND_SEND)


def test_anonymous_has_nothing():
    with pytest.raises(AuthorizationError):
        require_permission(None, Perm.VIEW_INSIGHTS)


def test_deactivated_user_loses_principal_immediately(engine, make_user):
    uid = make_user("temp", ["HR"])
    assert _principal(engine, uid) is not None
    with session_scope(engine) as s:
        SecurityRepository(s).get_user(uid).is_active = False
    assert _principal(engine, uid) is None


def test_role_permission_changes_take_effect_via_db(engine, settings, make_user):
    uid = make_user("ro", ["VIEWER"])
    assert _principal(engine, uid).permissions == {"VIEW_INSIGHTS"}
    changed = settings.security.model_copy(update={"roles": {
        **settings.security.roles, "VIEWER": settings.security.roles["VIEWER"].model_copy(update={"permissions": ()})}})
    with session_scope(engine) as s:
        SecurityRepository(s).sync_roles_and_permissions(changed)
    assert _principal(engine, uid).permissions == frozenset()
