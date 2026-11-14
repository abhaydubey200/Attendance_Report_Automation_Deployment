from __future__ import annotations

import pytest
import yaml

from core.config import load_attendance_rules, load_settings, load_source_authority, validate_all_configs
from core.exceptions import ConfigurationError
from ingestion.dataset_registry import SchemaStatus, load_dataset_registry


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


def test_sqlite_rejected_in_production(isolated_env, monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    with pytest.raises(ConfigurationError, match="SQLite is not permitted"):
        load_settings()


def test_email_cannot_be_enabled_outside_production(isolated_env, config_copy):
    _edit(config_copy / "settings.yaml", lambda d: d["features"].update(email_enabled=True))
    with pytest.raises(ConfigurationError, match="email_enabled"):
        load_settings(config_copy)


def test_ai_enabled_requires_model(isolated_env, config_copy):
    _edit(config_copy / "ai_config.yaml", lambda d: d.update(enabled=True, model=None))
    with pytest.raises(ConfigurationError, match="model"):
        load_settings(config_copy)


def test_unknown_permission_in_role_rejected(isolated_env, config_copy):
    _edit(config_copy / "security.yaml", lambda d: d["roles"]["HOD"]["permissions"].append("DO_ANYTHING"))
    with pytest.raises(ConfigurationError, match="unknown permissions"):
        load_settings(config_copy)


def test_unknown_database_profile_rejected(isolated_env, monkeypatch):
    monkeypatch.setenv("DB_PROFILE", "nope")
    with pytest.raises(ConfigurationError, match="not found"):
        load_settings()


def test_system_admin_has_no_hr_data_permissions(settings):
    perms = set(settings.security.roles["SYSTEM_ADMIN"].permissions)
    assert not {p for p in perms if p.startswith(("ATTENDANCE_", "REPORT_", "DATA_UPLOAD", "RECONCILIATION_"))}


def test_directors_lack_employee_level_access_by_default(settings):
    assert "ATTENDANCE_VIEW_EMPLOYEE" not in settings.security.roles["DIRECTOR"].permissions


def test_attendance_rules_are_draft_and_unresolved():
    rules = load_attendance_rules()
    assert rules.approval_status == "NOT_APPROVED"
    assert not rules.is_approved
    # Nothing may be pre-filled without HR approval.
    assert rules.calculation.unresolved_rules() == list(rules.calculation.model_dump())


def test_approved_rules_require_attribution(config_copy):
    _edit(config_copy / "attendance_rules.yaml", lambda d: d.update(approval_status="APPROVED"))
    with pytest.raises(ConfigurationError, match="approved_by"):
        load_attendance_rules(config_copy)


def test_source_authority_pending_and_validated(config_copy):
    authority = load_source_authority()
    assert all(d.authoritative_source is None for d in authority.domains.values())
    _edit(config_copy / "source_authority.yaml", lambda d: d["domains"]["APPROVED_LEAVE"].update(authoritative_source="SAP"))
    with pytest.raises(ConfigurationError, match="not a known source system"):
        load_source_authority(config_copy)


def test_dataset_registry_has_all_categories_pending_discovery():
    registry = load_dataset_registry()
    assert {d.dataset_id for d in registry.datasets} == {
        "BIZOM_ATTENDANCE", "HRMS_EMPLOYEE_MASTER", "HRMS_ATTENDANCE", "HRMS_LEAVE",
        "HRMS_PUNCH", "DEPARTMENT_MASTER", "REPORTING_HIERARCHY", "HOLIDAY_CALENDAR",
    }
    # No invented source columns.
    for d in registry.datasets:
        assert d.schema_status is SchemaStatus.PENDING_DISCOVERY
        assert d.required_columns == () and not d.ready_for_upload_validation


def test_defined_dataset_requires_columns(config_copy):
    _edit(config_copy / "datasets.yaml", lambda d: d["datasets"][0].update(schema_status="DEFINED"))
    with pytest.raises(ConfigurationError, match="required_columns"):
        load_dataset_registry(config_copy)


def test_missing_config_file_reported(config_copy):
    (config_copy / "recipients.yaml").unlink()
    errors = validate_all_configs(config_copy)
    assert any("recipients" in e for e in errors)
