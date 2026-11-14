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


def test_dataset_registry_categories_and_only_inspected_schemas():
    registry = load_dataset_registry()
    assert {d.dataset_id for d in registry.datasets} == {
        "HRMS_ATTENDANCE_SUMMARY", "BIZOM_ATTENDANCE", "HRMS_EMPLOYEE_MASTER", "HRMS_ATTENDANCE", "HRMS_LEAVE",
        "HRMS_PUNCH", "DEPARTMENT_MASTER", "REPORTING_HIERARCHY", "HOLIDAY_CALENDAR",
    }
    # Pocket HRMS only since 14-Nov-2026: Bizom kept but switched off.
    assert registry.get("BIZOM_ATTENDANCE").active is False
    # Only the AttendanceSummary has columns, and they come from the inspected real sample.
    summary = registry.get("HRMS_ATTENDANCE_SUMMARY")
    assert summary.schema_status is SchemaStatus.DEFINED and summary.seed_schema
    assert list(summary.required_columns) == ["Code", "Name", "Category", "Date", "Shift Name", "In-Out Time", "Type", "Day", "Remarks"]
    for d in registry.datasets:
        if d.dataset_id != "HRMS_ATTENDANCE_SUMMARY":
            assert d.schema_status is SchemaStatus.PENDING_DISCOVERY and d.required_columns == ()


def test_seed_schema_is_valid_and_leaves_hr_decisions_unmapped():
    from ingestion.schema_definition import SchemaDefinition

    seed = load_dataset_registry().get("HRMS_ATTENDANCE_SUMMARY").seed_schema
    definition = SchemaDefinition.model_validate(seed["definition"])
    assert definition.validate_for("HRMS_ATTENDANCE_SUMMARY") == []
    status_map = definition.value_maps["source_status"]
    for open_question in ("NO_PUNCH", "NO_PUNCH_NO_SHIFT", "LEAVE:LD"):
        assert open_question not in status_map
    assert "PROPOSAL" in seed["notes"]


def test_defined_dataset_requires_columns(config_copy):
    _edit(config_copy / "datasets.yaml",
          lambda d: next(x for x in d["datasets"] if x["dataset_id"] == "HRMS_LEAVE").update(schema_status="DEFINED"))
    with pytest.raises(ConfigurationError, match="required_columns"):
        load_dataset_registry(config_copy)


def test_missing_config_file_reported(config_copy):
    (config_copy / "recipients.yaml").unlink()
    errors = validate_all_configs(config_copy)
    assert any("recipients" in e for e in errors)


def test_production_requires_secret_key_and_secure_cookie(isolated_env, monkeypatch, config_copy):
    import yaml as _yaml

    db = config_copy / "database.yaml"
    data = _yaml.safe_load(db.read_text())
    data["profiles"]["mssql"]["driver"] = "x"
    db.write_text(_yaml.safe_dump(data))
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("DB_PROFILE", "mssql")
    monkeypatch.setenv("AUTH_MODE", "local")
    with pytest.raises(ConfigurationError, match="APP_SECRET_KEY"):
        load_settings(config_copy)
    monkeypatch.setenv("APP_SECRET_KEY", "k" * 40)
    with pytest.raises(ConfigurationError, match="cookie_secure"):
        load_settings(config_copy)
    _edit(config_copy / "settings.yaml", lambda d: d["api"].update(cookie_secure=True))
    assert load_settings(config_copy).environment == "production"


def test_secret_key_cannot_live_in_yaml(isolated_env, config_copy):
    _edit(config_copy / "settings.yaml", lambda d: d["api"].update(secret_key="oops"))
    with pytest.raises(ConfigurationError, match="APP_SECRET_KEY"):
        load_settings(config_copy)


def test_wildcard_cors_rejected(isolated_env, config_copy):
    _edit(config_copy / "settings.yaml", lambda d: d["api"].update(cors_origins=["*"]))
    with pytest.raises(ConfigurationError, match="wildcard"):
        load_settings(config_copy)


def test_no_login_mode_forbidden_in_production(isolated_env, monkeypatch, config_copy):
    _edit(config_copy / "database.yaml", lambda d: d.update(default_profile="mssql"))
    _edit(config_copy / "settings.yaml", lambda d: d["api"].update(cookie_secure=True))
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("APP_SECRET_KEY", "k" * 40)
    monkeypatch.delenv("DB_PROFILE", raising=False)
    with pytest.raises(ConfigurationError, match="not permitted in production"):
        load_settings(config_copy)


def test_no_login_mode_requires_localhost(isolated_env, monkeypatch):
    monkeypatch.setenv("API_HOST", "0.0.0.0")
    with pytest.raises(ConfigurationError, match="localhost"):
        load_settings()
    monkeypatch.setenv("AUTH_MODE", "local")
    assert load_settings().api.host == "0.0.0.0"


def test_no_login_default_user_roles_validated(isolated_env, config_copy):
    _edit(config_copy / "settings.yaml", lambda d: d["auth"]["default_user"].update(roles=["GOD_MODE"]))
    with pytest.raises(ConfigurationError, match="unknown roles"):
        load_settings(config_copy)


def test_shipped_default_is_no_login_on_localhost(settings):
    assert settings.auth.mode == "none" and settings.api.host == "127.0.0.1"
