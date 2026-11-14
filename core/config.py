"""Configuration loading and validation.

All YAML files in ``config/`` are parsed into validated Pydantic models.
Secrets are read only from environment variables (optionally via a local ``.env``).
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal, Mapping

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from contracts.attendance import AttendanceStatus
from core.exceptions import ConfigurationError
from core.paths import CONFIG_DIR, PROJECT_ROOT, resolve_path

Environment = Literal["development", "testing", "production"]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


# --------------------------------------------------------------------------- settings.yaml
class AppSection(_Strict):
    name: str
    short_name: str
    timezone: str = "Asia/Kolkata"
    date_format: str = "%d-%b-%Y"
    datetime_format: str = "%d-%b-%Y %H:%M"
    environment: Environment = "development"


class StorageSection(_Strict):
    base_dir: Path
    uploads: str = "uploads"
    raw: str = "raw"
    processed: str = "processed"
    reports: str = "reports"
    archive: str = "archive"

    def area(self, name: str) -> Path:
        return self.base_dir / getattr(self, name)

    def all_areas(self) -> dict[str, Path]:
        return {n: self.area(n) for n in ("uploads", "raw", "processed", "reports", "archive")}


class LoggingSection(_Strict):
    dir: Path
    level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    file_name: str = "app.log"
    max_bytes: int = Field(default=10 * 1024 * 1024, gt=0)
    backup_count: int = Field(default=10, ge=0)
    json_format: bool = Field(default=True, alias="json")

    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)


class UploadSection(_Strict):
    max_file_size_mb: int = Field(gt=0, le=500)
    allowed_extensions: tuple[str, ...]

    @field_validator("allowed_extensions")
    @classmethod
    def _lower_dotted(cls, v: tuple[str, ...]) -> tuple[str, ...]:
        for ext in v:
            if not ext.startswith(".") or ext != ext.lower():
                raise ValueError(f"extension must be lowercase and start with '.': {ext!r}")
        return v


class SessionSection(_Strict):
    idle_timeout_minutes: int = Field(gt=0)
    max_failed_logins: int = Field(gt=0)
    lockout_minutes: int = Field(gt=0)
    min_password_length: int = Field(ge=8)


class FeatureSection(_Strict):
    email_enabled: bool = False
    ai_enabled: bool = False


# --------------------------------------------------------------------------- database.yaml
class DatabaseProfile(_Strict):
    name: str
    backend: Literal["sqlite", "mssql"]
    # sqlite
    path: Path | None = None
    # mssql (non-secret defaults; secrets come from env)
    driver: str | None = None
    port: int | None = None
    encrypt: bool = True
    trust_server_certificate: bool = False
    connect_timeout_seconds: int = 15
    pool_size: int = 5
    max_overflow: int = 5


# --------------------------------------------------------------------------- security.yaml
class RoleDefinition(_Strict):
    description: str
    permissions: tuple[str, ...]


class SecurityConfig(_Strict):
    approval_status: str
    permissions: dict[str, str]
    roles: dict[str, RoleDefinition]

    @model_validator(mode="after")
    def _roles_reference_known_permissions(self) -> "SecurityConfig":
        required_roles = {"SYSTEM_ADMIN", "HR_ADMIN", "HR_MANAGER", "HOD", "DIRECTOR", "READ_ONLY"}
        missing = required_roles - set(self.roles)
        if missing:
            raise ValueError(f"missing mandatory roles: {sorted(missing)}")
        for role, definition in self.roles.items():
            unknown = set(definition.permissions) - set(self.permissions)
            if unknown:
                raise ValueError(f"role {role} references unknown permissions: {sorted(unknown)}")
        return self


# --------------------------------------------------------------------------- ai_config.yaml
class AIConfig(_Strict):
    enabled: bool = False
    provider: Literal["ollama"] = "ollama"
    endpoint: str
    model: str | None = None
    timeout_seconds: int = Field(default=30, gt=0)
    max_retries: int = Field(default=1, ge=0, le=5)
    prompt_version: str

    @model_validator(mode="after")
    def _model_required_when_enabled(self) -> "AIConfig":
        if self.enabled and not self.model:
            raise ValueError("ai_config: 'model' must be set when AI is enabled")
        return self


# --------------------------------------------------------------------------- attendance_rules.yaml
class AttendanceCalculationRules(_Strict):
    half_day_equivalent: float | None = None
    wfh_counts_as_present: bool | None = None
    approved_leave_in_denominator: bool | None = None
    include_weekly_off_in_denominator: bool | None = None
    include_holidays_in_denominator: bool | None = None
    contractor_treatment: str | None = None
    new_joiner_treatment: str | None = None
    exit_treatment: str | None = None
    overnight_shift_policy: str | None = None
    reporting_period_d_minus_1: Literal["CALENDAR_DAY", "WORKING_DAY"] | None = None

    def unresolved_rules(self) -> list[str]:
        return [name for name, value in self.model_dump().items() if value is None]


class AttendanceRules(_Strict):
    rule_version: str
    approval_status: Literal["NOT_APPROVED", "APPROVED"]
    approved_by: str | None = None
    approved_on: str | None = None
    timezone: str
    statuses: tuple[AttendanceStatus, ...]
    calculation: AttendanceCalculationRules

    @model_validator(mode="after")
    def _approval_requires_attribution(self) -> "AttendanceRules":
        if self.approval_status == "APPROVED" and not (self.approved_by and self.approved_on):
            raise ValueError("APPROVED rules must record approved_by and approved_on")
        return self

    @property
    def is_approved(self) -> bool:
        return self.approval_status == "APPROVED" and not self.calculation.unresolved_rules()


# --------------------------------------------------------------------------- source_authority.yaml
class SourceDomain(_Strict):
    proposed_source: str | None = None
    authoritative_source: str | None = None


class SourceAuthority(_Strict):
    approval_status: Literal["NOT_APPROVED", "APPROVED"]
    domains: dict[str, SourceDomain]


# --------------------------------------------------------------------------- aggregate
class Settings(_Strict):
    app: AppSection
    storage: StorageSection
    logging: LoggingSection
    uploads: UploadSection
    session: SessionSection
    features: FeatureSection
    database: DatabaseProfile
    security: SecurityConfig
    ai: AIConfig
    config_dir: Path

    @property
    def environment(self) -> Environment:
        return self.app.environment

    @model_validator(mode="after")
    def _environment_rules(self) -> "Settings":
        if self.environment == "production" and self.database.backend == "sqlite":
            raise ValueError("SQLite is not permitted in production (PRD 10.1); select an mssql profile")
        if self.environment != "production" and self.features.email_enabled:
            raise ValueError("email_enabled must be false outside production (PRD 24.3)")
        if self.features.ai_enabled and not self.ai.enabled:
            raise ValueError("features.ai_enabled is true but ai_config.enabled is false")
        return self


# --------------------------------------------------------------------------- loaders
def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise ConfigurationError(f"Configuration file not found: {path}")
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ConfigurationError(f"Invalid YAML in {path.name}: {exc}") from exc
    if not isinstance(data, dict):
        raise ConfigurationError(f"{path.name} must contain a mapping at the top level")
    return data


def _validate(model: type[BaseModel], data: Mapping[str, Any], source: str):
    try:
        return model.model_validate(data)
    except ValidationError as exc:
        raise ConfigurationError(f"{source}: {exc}") from exc


def load_dotenv_if_present() -> None:
    """Load a local .env (development convenience). Real environment variables win."""
    try:
        from dotenv import load_dotenv
    except ImportError:  # pragma: no cover
        return
    load_dotenv(PROJECT_ROOT / ".env", override=False)


def load_settings(config_dir: Path | None = None, env: Mapping[str, str] | None = None) -> Settings:
    """Build validated Settings from YAML files plus environment overrides."""
    config_dir = Path(config_dir or CONFIG_DIR)
    env = os.environ if env is None else env

    raw = _read_yaml(config_dir / "settings.yaml")
    app = dict(raw.get("app", {}))
    storage = dict(raw.get("storage", {}))
    logging_cfg = dict(raw.get("logging", {}))

    if env.get("APP_ENV"):
        app["environment"] = env["APP_ENV"]
    storage["base_dir"] = resolve_path(env.get("APP_STORAGE_DIR") or storage.get("base_dir", "storage"))
    logging_cfg["dir"] = resolve_path(env.get("APP_LOG_DIR") or logging_cfg.get("dir", "logs"))
    if env.get("APP_LOG_LEVEL"):
        logging_cfg["level"] = env["APP_LOG_LEVEL"].upper()

    db_raw = _read_yaml(config_dir / "database.yaml")
    profile_name = env.get("DB_PROFILE") or db_raw.get("default_profile")
    profiles = db_raw.get("profiles", {})
    if profile_name not in profiles:
        raise ConfigurationError(f"database profile {profile_name!r} not found in database.yaml")
    profile = {"name": profile_name, **profiles[profile_name]}
    if profile.get("backend") == "sqlite":
        profile["path"] = resolve_path(env.get("DB_SQLITE_PATH") or profile.get("path") or "storage/dev/dev.db")
    if env.get("DB_DRIVER"):
        profile["driver"] = env["DB_DRIVER"]
    if env.get("DB_TRUST_SERVER_CERT"):
        profile["trust_server_certificate"] = env["DB_TRUST_SERVER_CERT"].strip().lower() in {"1", "yes", "true"}

    ai_raw = _read_yaml(config_dir / "ai_config.yaml")
    if env.get("AI_ENDPOINT"):
        ai_raw["endpoint"] = env["AI_ENDPOINT"]

    data = {
        "app": app,
        "storage": storage,
        "logging": logging_cfg,
        "uploads": raw.get("uploads", {}),
        "session": raw.get("session", {}),
        "features": raw.get("features", {}),
        "database": profile,
        "security": _read_yaml(config_dir / "security.yaml"),
        "ai": ai_raw,
        "config_dir": config_dir,
    }
    return _validate(Settings, data, "settings")


def load_attendance_rules(config_dir: Path | None = None) -> AttendanceRules:
    path = Path(config_dir or CONFIG_DIR) / "attendance_rules.yaml"
    return _validate(AttendanceRules, _read_yaml(path), path.name)


def load_source_authority(config_dir: Path | None = None) -> SourceAuthority:
    config_dir = Path(config_dir or CONFIG_DIR)
    authority = _validate(SourceAuthority, _read_yaml(config_dir / "source_authority.yaml"), "source_authority.yaml")
    known = set(_read_yaml(config_dir / "datasets.yaml").get("source_systems", {}))
    for domain, value in authority.domains.items():
        for field in ("proposed_source", "authoritative_source"):
            src = getattr(value, field)
            if src is not None and src not in known:
                raise ConfigurationError(f"source_authority.yaml: {domain}.{field}={src!r} is not a known source system")
    return authority


def load_recipients(config_dir: Path | None = None) -> dict[str, Any]:
    return _read_yaml(Path(config_dir or CONFIG_DIR) / "recipients.yaml")


def validate_all_configs(config_dir: Path | None = None, env: Mapping[str, str] | None = None) -> list[str]:
    """Validate every configuration file. Returns a list of error messages (empty = valid)."""
    from ingestion.dataset_registry import load_dataset_registry

    errors: list[str] = []
    checks = (
        ("settings", lambda: load_settings(config_dir, env)),
        ("datasets", lambda: load_dataset_registry(config_dir)),
        ("attendance_rules", lambda: load_attendance_rules(config_dir)),
        ("source_authority", lambda: load_source_authority(config_dir)),
        ("recipients", lambda: load_recipients(config_dir)),
    )
    for name, check in checks:
        try:
            check()
        except ConfigurationError as exc:
            errors.append(f"[{name}] {exc}")
    return errors


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Process-wide settings (cached). Call ``get_settings.cache_clear()`` in tests."""
    load_dotenv_if_present()
    return load_settings()
