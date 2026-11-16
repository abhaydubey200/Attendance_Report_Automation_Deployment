from __future__ import annotations

import pytest
import yaml

from core.config import Rules, load_settings, validate_all_configs
from core.exceptions import ConfigurationError


def _edit(path, mutate):
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    mutate(data)
    path.write_text(yaml.safe_dump(data), encoding="utf-8")


def test_shipped_configuration_is_valid(isolated_env):
    assert validate_all_configs() == []


def test_env_overrides_are_applied(settings, isolated_env):
    assert settings.environment == "testing"
    assert str(settings.storage.base_dir) == isolated_env["APP_STORAGE_DIR"]
    assert str(settings.database.path) == isolated_env["DB_SQLITE_PATH"]


def test_default_rules_and_email(settings):
    assert settings.rules.late_after == "09:30" and settings.rules.no_punch_no_shift == "NOT_TRACKED"
    assert "^test$" in settings.rules.exclude_codes
    assert settings.email.mode == "test" and settings.email.auto_send is True


def test_rules_validation():
    with pytest.raises(ValueError):
        Rules(late_after="9.30")
    with pytest.raises(ValueError, match="invalid exclusion pattern"):
        Rules(exclude_codes=["(unclosed"])


def test_production_guards(isolated_env, monkeypatch, config_copy):
    monkeypatch.setenv("APP_ENV", "production")
    with pytest.raises(ConfigurationError, match="SQLite"):
        load_settings(config_copy)
    _edit(config_copy / "database.yaml", lambda d: d.update(default_profile="mssql"))
    monkeypatch.delenv("DB_PROFILE", raising=False)
    monkeypatch.setenv("AUTH_MODE", "local")
    with pytest.raises(ConfigurationError, match="APP_SECRET_KEY"):
        load_settings(config_copy)
    monkeypatch.setenv("APP_SECRET_KEY", "k" * 40)
    with pytest.raises(ConfigurationError, match="cookie_secure"):
        load_settings(config_copy)
    _edit(config_copy / "settings.yaml", lambda d: d["api"].update(cookie_secure=True))
    assert load_settings(config_copy).environment == "production"
    monkeypatch.setenv("AUTH_MODE", "none")
    with pytest.raises(ConfigurationError, match="not permitted in production"):
        load_settings(config_copy)


def test_no_login_mode_requires_localhost(isolated_env, monkeypatch):
    monkeypatch.setenv("API_HOST", "0.0.0.0")
    with pytest.raises(ConfigurationError, match="localhost"):
        load_settings()
    monkeypatch.setenv("AUTH_MODE", "local")
    assert load_settings().api.host == "0.0.0.0"


def test_secret_key_cannot_live_in_yaml(isolated_env, config_copy):
    _edit(config_copy / "settings.yaml", lambda d: d["api"].update(secret_key="oops"))
    with pytest.raises(ConfigurationError, match="APP_SECRET_KEY"):
        load_settings(config_copy)


def test_wildcard_cors_rejected(isolated_env, config_copy):
    _edit(config_copy / "settings.yaml", lambda d: d["api"].update(cors_origins=["*"]))
    with pytest.raises(ConfigurationError, match="wildcard"):
        load_settings(config_copy)


def test_unknown_permission_in_role_rejected(isolated_env, config_copy):
    _edit(config_copy / "security.yaml", lambda d: d["roles"]["HR"]["permissions"].append("DO_ANYTHING"))
    with pytest.raises(ConfigurationError, match="unknown permissions"):
        load_settings(config_copy)


def test_missing_config_file_reported(config_copy):
    (config_copy / "security.yaml").unlink()
    assert any("security.yaml" in e for e in validate_all_configs(config_copy))



def test_production_profile_on_sqlite(isolated_env, monkeypatch, tmp_path):
    """The Windows Server setup: production on the sqlite_prod profile, sign-in, HTTPS cookie, data outside the code."""
    from core.config import load_settings

    for k, v in {"APP_ENV": "production", "DB_PROFILE": "sqlite_prod", "DB_SQLITE_PATH": str(tmp_path / "attendance.db"),
                 "AUTH_MODE": "local", "APP_SECRET_KEY": "x" * 48, "API_COOKIE_SECURE": "true",
                 "APP_INBOX_DIR": str(tmp_path / "inbox")}.items():
        monkeypatch.setenv(k, v)
    s = load_settings()
    assert s.environment == "production" and s.database.production and s.api.cookie_secure
    assert s.jobs.inbox_dir == tmp_path / "inbox"
    monkeypatch.setenv("DB_PROFILE", "dev_sqlite")
    with pytest.raises(Exception, match="development SQLite profile"):
        load_settings()
