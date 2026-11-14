from __future__ import annotations

import pytest

from core.exceptions import AuthorizationError
from database.connection import session_scope
from database.repositories.security_repository import SecurityRepository
from security.authorization import (
    can_access_department,
    can_view_employee_records,
    require_department_access,
    require_permission,
    scope_departments,
)
from security.permissions import Perm


def _principal(engine, user_id):
    with session_scope(engine) as s:
        return SecurityRepository(s).load_principal(user_id)


def test_hod_is_isolated_to_assigned_departments(engine, make_user):
    hod = _principal(engine, make_user("hod.sales", ["HOD"], departments=["sales"]))
    assert hod.departments == {"SALES"}
    assert can_access_department(hod, "SALES") and not can_access_department(hod, "FINANCE")
    assert can_view_employee_records(hod, "SALES") and not can_view_employee_records(hod, "FINANCE")
    assert scope_departments(hod, ["SALES", "FINANCE", "HR"]) == ["SALES"]
    with pytest.raises(AuthorizationError):
        require_department_access(hod, "FINANCE")
    with pytest.raises(AuthorizationError):
        require_permission(hod, Perm.REPORT_VIEW_DIRECTORS)


def test_director_sees_all_departments_but_not_employee_level(engine, make_user):
    director = _principal(engine, make_user("dir", ["DIRECTOR"]))
    assert can_access_department(director, "ANY")
    assert not can_view_employee_records(director, "ANY")


def test_system_admin_has_no_hr_data_access(engine, make_user):
    admin = _principal(engine, make_user("sysadmin", ["SYSTEM_ADMIN"]))
    require_permission(admin, Perm.ADMIN_USERS)
    for perm in (Perm.DASHBOARD_VIEW, Perm.ATTENDANCE_VIEW_EMPLOYEE, Perm.REPORT_VIEW_HOD, Perm.DATA_UPLOAD):
        with pytest.raises(AuthorizationError):
            require_permission(admin, perm)
    assert not can_access_department(admin, "SALES")


def test_anonymous_has_nothing():
    with pytest.raises(AuthorizationError):
        require_permission(None, Perm.DASHBOARD_VIEW)
    assert not can_access_department(None, "SALES")


def test_deactivated_user_loses_principal_immediately(engine, make_user):
    uid = make_user("temp", ["HR_ADMIN"])
    assert _principal(engine, uid) is not None
    with session_scope(engine) as s:
        SecurityRepository(s).get_user(uid).is_active = False
    assert _principal(engine, uid) is None


def test_role_permission_changes_take_effect_via_db(engine, settings, make_user):
    """Permissions are read from the central DB store, not cached config."""
    uid = make_user("ro", ["READ_ONLY"])
    assert _principal(engine, uid).permissions == {"DASHBOARD_VIEW"}
    changed = settings.security.model_copy(
        update={"roles": {**settings.security.roles,
                          "READ_ONLY": settings.security.roles["READ_ONLY"].model_copy(update={"permissions": ()})}}
    )
    with session_scope(engine) as s:
        SecurityRepository(s).sync_roles_and_permissions(changed)
    assert _principal(engine, uid).permissions == frozenset()
