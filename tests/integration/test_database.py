from __future__ import annotations

import pytest
from sqlalchemy import func, inspect, select

from database.connection import check_database, session_scope
from database.migrate import head_revision, upgrade_to_head
from database.models.security import AppRole, RolePermission
from database.repositories.security_repository import SecurityRepository


def test_migration_creates_tables_and_is_idempotent(engine, settings):
    tables = set(inspect(engine).get_table_names())
    assert {"app_user", "app_role", "permission", "user_role", "role_permission",
            "user_department_access", "user_activity_log"} <= tables
    upgrade_to_head(engine)  # re-running is a no-op
    status = check_database(engine, settings)
    assert status.reachable and status.schema_revision == head_revision()


def test_role_sync_is_idempotent(engine, settings):
    with session_scope(engine) as s:
        SecurityRepository(s).sync_roles_and_permissions(settings.security)
    with session_scope(engine) as s:
        assert s.scalar(select(func.count()).select_from(AppRole)) == len(settings.security.roles)
        expected = sum(len(r.permissions) for r in settings.security.roles.values())
        assert s.scalar(select(func.count()).select_from(RolePermission)) == expected


def test_session_scope_rolls_back_on_error(engine, make_user):
    with pytest.raises(RuntimeError):
        with session_scope(engine) as s:
            SecurityRepository(s).create_user("ghost", "Ghost", None, ["READ_ONLY"])
            raise RuntimeError("boom")
    with session_scope(engine) as s:
        assert SecurityRepository(s).get_user_by_username("ghost") is None


def test_duplicate_username_rejected_case_insensitively(engine, make_user):
    make_user("alice", ["READ_ONLY"])
    with pytest.raises(ValueError, match="already exists"):
        make_user("ALICE", ["READ_ONLY"])


def test_unknown_role_rejected(engine, make_user):
    with pytest.raises(ValueError, match="unknown roles"):
        make_user("bob", ["SUPERUSER"])


def test_foreign_keys_enforced_on_sqlite(engine):
    from sqlalchemy import text
    from sqlalchemy.exc import IntegrityError

    with pytest.raises(IntegrityError):
        with engine.begin() as conn:
            conn.execute(text("INSERT INTO user_role (user_id, role_id, granted_at) VALUES (999, 999, CURRENT_TIMESTAMP)"))


def test_check_database_reports_unreachable(settings, tmp_path):
    from sqlalchemy import create_engine

    bad = create_engine(f"sqlite:///{tmp_path / 'missing_dir' / 'x.db'}")
    status = check_database(bad, settings)
    assert not status.reachable and "connection failed" in status.detail
