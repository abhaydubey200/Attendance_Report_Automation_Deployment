"""Shared fixtures. Tests never touch the real storage/, logs/ or development database,
and never use real employee data."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from core.config import Settings, get_settings, load_settings
from core.paths import CONFIG_DIR

TEST_PASSWORD = "Test-Passw0rd-Only!"


@pytest.fixture(autouse=True)
def _detach_app_log_handlers():
    """configure_logging() attaches root handlers once per process; remove them after
    each test so tests stay independent and temp log files can be deleted."""
    import logging

    from core.logging_setup import _HANDLER_TAG

    yield
    root = logging.getLogger()
    for handler in [h for h in root.handlers if getattr(h, _HANDLER_TAG, False)]:
        root.removeHandler(handler)
        handler.close()


@pytest.fixture
def isolated_env(tmp_path, monkeypatch) -> dict[str, str]:
    env = {
        "APP_ENV": "testing",
        "APP_STORAGE_DIR": str(tmp_path / "storage"),
        "APP_LOG_DIR": str(tmp_path / "logs"),
        "DB_PROFILE": "dev_sqlite",
        "DB_SQLITE_PATH": str(tmp_path / "test.db"),
    }
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    for key in ("DB_HOST", "DB_NAME", "DB_USER", "DB_PASSWORD", "DB_TRUSTED_CONNECTION", "DB_DRIVER", "AI_ENDPOINT", "APP_SECRET_KEY", "API_HOST", "API_PORT"):
        monkeypatch.delenv(key, raising=False)
    get_settings.cache_clear()
    yield env
    get_settings.cache_clear()


@pytest.fixture
def settings(isolated_env) -> Settings:
    return load_settings()


@pytest.fixture
def config_copy(tmp_path) -> Path:
    """A writable copy of config/ for tests that mutate configuration."""
    dest = tmp_path / "config"
    shutil.copytree(CONFIG_DIR, dest)
    return dest


@pytest.fixture
def engine(settings):
    from database.connection import create_db_engine, session_scope
    from database.migrate import upgrade_to_head
    from database.repositories.security_repository import SecurityRepository

    eng = create_db_engine(settings)
    upgrade_to_head(eng)
    with session_scope(eng) as s:
        SecurityRepository(s).sync_roles_and_permissions(settings.security)
    yield eng
    eng.dispose()


@pytest.fixture
def make_user(engine):
    from database.connection import session_scope
    from database.repositories.security_repository import SecurityRepository
    from security.authentication import hash_password

    hashed = hash_password(TEST_PASSWORD)  # hash once; bcrypt is deliberately slow

    def _make(username: str, roles: list[str], departments: list[str] | None = None, active: bool = True) -> int:
        with session_scope(engine) as s:
            user = SecurityRepository(s).create_user(username, username.title(), hashed, roles, departments)
            user.is_active = active
            return user.user_id

    return _make
