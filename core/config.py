"""Configuration loading and validation.

`config/settings.yaml` holds defaults; the counting rules, recipients and email
options a user changes in the Settings screen are stored in the database and
override the defaults (see `daily/settings_store.py`). Secrets come only from
environment variables (optionally a local `.env`).
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal, Mapping

import yaml
from pydantic import BaseModel, ConfigDict, Field, SecretStr, ValidationError, field_validator, model_validator

from core.exceptions import ConfigurationError
from core.paths import CONFIG_DIR, resolve_path

Environment = Literal["development", "testing", "production"]
LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class AppSection(_Strict):
    name: str
    short_name: str
    company: str = "APIS India Limited"
    timezone: str = "Asia/Kolkata"
    date_format: str = "%d-%b-%Y"
    datetime_format: str = "%d-%b-%Y %H:%M"
    environment: Environment = "development"
    public_url: str | None = None          # link to this app in emails (intranet URL)


class StorageSection(_Strict):
    base_dir: Path

    def area(self, name: str) -> Path:
        return self.base_dir / name


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


class Rules(BaseModel):
    """How a day is counted. Defaults here; edited in Settings (stored in the database)."""

    model_config = ConfigDict(extra="forbid")

    late_after: str = Field(default="09:30", pattern=r"^\d{2}:\d{2}$")
    early_before: str = Field(default="18:00", pattern=r"^\d{2}:\d{2}$")
    min_work_hours: float = Field(default=8.0, ge=0, le=24)
    long_work_hours: float = Field(default=11.0, ge=0, le=24)
    on_duty_codes: list[str] = Field(default_factory=lambda: ["LD", "OD"])
    wfh_codes: list[str] = Field(default_factory=lambda: ["WFH", "WH"])
    no_punch_with_shift: Literal["ABSENT", "NOT_TRACKED"] = "ABSENT"
    no_punch_no_shift: Literal["ABSENT", "NOT_TRACKED"] = "NOT_TRACKED"
    single_punch_counts_present: bool = True
    exclude_codes: list[str] = Field(default_factory=list)
    bizom_include_codes: list[str] = Field(default_factory=lambda: ["^AP"])   # Bizom-only users to report besides the master

    @field_validator("exclude_codes", "bizom_include_codes")
    @classmethod
    def _valid_patterns(cls, v: list[str]) -> list[str]:
        import re

        for pattern in v:
            try:
                re.compile(pattern)
            except re.error as exc:
                raise ValueError(f"invalid exclusion pattern {pattern!r}: {exc}") from None
        return v


class EmailSettings(BaseModel):
    """Email options. Secrets are never stored here: SMTP_PASSWORD, GRAPH_* and GMAIL_* come from the environment.

    Routing (who gets what) comes from the employee master; these switches mirror the
    Email_Routing_Config sheet of HR's routing workbook and can be changed in Settings."""

    model_config = ConfigDict(extra="forbid")

    mode: Literal["test", "live"] = "test"            # test = save .eml files to the outbox; live = deliver
    provider: Literal["smtp", "graph", "gmail"] = "gmail"   # APIS uses the Gmail API
    approval_required: bool = True     # preview mode: emails wait on the Approve screen until someone approves
    auto_send: bool = True             # when approval is off: send right after the upload
    wait_for_bizom: bool = True        # only prepare/send once both the Pocket HRMS and Bizom files of the day are in
    sender: str | None = None          # one central mailbox, e.g. attendance@<company domain>
    reply_to: str | None = None
    smtp_host: str | None = None
    smtp_port: int = Field(default=587, gt=0, lt=65536)
    smtp_starttls: bool = True
    smtp_username: str | None = None
    subject_prefix: str = "Daily Attendance"
    attach_excel: bool = True
    attach_dashboard: bool = True
    retry_attempts: int = Field(default=3, ge=1, le=5)
    # routing switches (Email_Routing_Config)
    team_emails: bool = True           # team lead (Sub split ID) gets their own team's detail
    hod_summary: bool = True           # each HOD gets a summary of everyone under them
    director_report: bool = True       # Director gets the company summary by HOD (+ Director Office staff)
    hr_exceptions: bool = True         # HR gets records that cannot be routed (only on days with any)
    hod_cc_on_team: bool = False       # CC the HOD on team-lead emails (needs HR approval)
    hr_cc_on_hod_summary: bool = False
    director_name: str = "Director"
    director_emails: list[str] = Field(default_factory=list)
    hr_emails: list[str] = Field(default_factory=list)


class ApiSection(_Strict):
    host: str = "127.0.0.1"
    port: int = Field(default=8000, gt=0, lt=65536)
    cookie_name: str = "apis_mis_session"
    cookie_secure: bool = False
    cors_origins: tuple[str, ...] = ()
    frame_ancestors: tuple[str, ...] = ("'self'",)
    serve_frontend: bool = True
    secret_key: SecretStr | None = None            # only from env APP_SECRET_KEY

    @field_validator("cors_origins")
    @classmethod
    def _no_wildcard(cls, v: tuple[str, ...]) -> tuple[str, ...]:
        if "*" in v:
            raise ValueError("wildcard CORS origin is not allowed with cookie authentication")
        return v


class DefaultUser(_Strict):
    username: str = Field(min_length=1, max_length=100)
    display_name: str
    roles: tuple[str, ...] = Field(min_length=1)


class AuthSection(_Strict):
    mode: Literal["none", "local"] = "local"
    default_user: DefaultUser | None = None

    @model_validator(mode="after")
    def _default_user_for_none(self) -> "AuthSection":
        if self.mode == "none" and self.default_user is None:
            raise ValueError("auth.mode 'none' requires auth.default_user")
        return self


class DatabaseProfile(_Strict):
    name: str
    backend: Literal["sqlite", "mssql"]
    path: Path | None = None
    driver: str | None = None
    port: int | None = None
    encrypt: bool = True
    trust_server_certificate: bool = False
    connect_timeout_seconds: int = 15
    pool_size: int = 5
    max_overflow: int = 5


class RoleDefinition(_Strict):
    description: str
    permissions: tuple[str, ...]


class SecurityConfig(_Strict):
    permissions: dict[str, str]
    roles: dict[str, RoleDefinition]

    @model_validator(mode="after")
    def _roles_reference_known_permissions(self) -> "SecurityConfig":
        for role, definition in self.roles.items():
            unknown = set(definition.permissions) - set(self.permissions)
            if unknown:
                raise ValueError(f"role {role} references unknown permissions: {sorted(unknown)}")
        return self


class Settings(_Strict):
    app: AppSection
    storage: StorageSection
    logging: LoggingSection
    uploads: UploadSection
    session: SessionSection
    rules: Rules
    email: EmailSettings
    api: ApiSection
    auth: AuthSection
    database: DatabaseProfile
    security: SecurityConfig
    config_dir: Path

    @property
    def environment(self) -> Environment:
        return self.app.environment

    @model_validator(mode="after")
    def _environment_rules(self) -> "Settings":
        if self.environment == "production":
            if self.database.backend == "sqlite":
                raise ValueError("SQLite is not permitted in production; select an mssql profile")
            key = self.api.secret_key.get_secret_value() if self.api.secret_key else ""
            if len(key) < 32:
                raise ValueError("APP_SECRET_KEY (>= 32 characters) is required in production")
            if not self.api.cookie_secure:
                raise ValueError("api.cookie_secure must be true in production (HTTPS)")
        if self.auth.mode == "none":
            if self.environment == "production":
                raise ValueError("auth.mode 'none' (no login) is not permitted in production")
            if self.api.host not in LOOPBACK_HOSTS:
                raise ValueError("auth.mode 'none' requires api.host to be localhost (127.0.0.1); "
                                 "use auth.mode 'local' to serve other machines")
            assert self.auth.default_user is not None
            unknown = set(self.auth.default_user.roles) - set(self.security.roles)
            if unknown:
                raise ValueError(f"auth.default_user has unknown roles: {sorted(unknown)}")
        return self


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


def load_dotenv_if_present() -> None:
    try:
        from dotenv import load_dotenv
    except ImportError:  # pragma: no cover
        return
    from core.paths import PROJECT_ROOT

    load_dotenv(PROJECT_ROOT / ".env", override=False)


def load_settings(config_dir: Path | None = None, env: Mapping[str, str] | None = None) -> Settings:
    config_dir = Path(config_dir or CONFIG_DIR)
    env = os.environ if env is None else env

    raw = _read_yaml(config_dir / "settings.yaml")
    app = dict(raw.get("app", {}))
    storage = dict(raw.get("storage", {}))
    logging_cfg = dict(raw.get("logging", {}))
    if env.get("APP_ENV"):
        app["environment"] = env["APP_ENV"]
    if env.get("APP_PUBLIC_URL"):
        app["public_url"] = env["APP_PUBLIC_URL"]
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

    api_cfg = dict(raw.get("api", {}))
    if "secret_key" in api_cfg:
        raise ConfigurationError("settings.yaml must not contain api.secret_key; use env APP_SECRET_KEY")
    if env.get("APP_SECRET_KEY"):
        api_cfg["secret_key"] = env["APP_SECRET_KEY"]
    if env.get("API_HOST"):
        api_cfg["host"] = env["API_HOST"]
    if env.get("API_PORT"):
        api_cfg["port"] = env["API_PORT"]
    auth_cfg = dict(raw.get("auth", {}))
    if env.get("AUTH_MODE"):
        auth_cfg["mode"] = env["AUTH_MODE"].strip().lower()

    data = {
        "app": app, "storage": storage, "logging": logging_cfg,
        "uploads": raw.get("uploads", {}), "session": raw.get("session", {}),
        "rules": raw.get("rules", {}), "email": raw.get("email", {}),
        "api": api_cfg, "auth": auth_cfg, "database": profile,
        "security": _read_yaml(config_dir / "security.yaml"), "config_dir": config_dir,
    }
    try:
        return Settings.model_validate(data)
    except ValidationError as exc:
        raise ConfigurationError(f"settings: {exc}") from exc


def validate_all_configs(config_dir: Path | None = None, env: Mapping[str, str] | None = None) -> list[str]:
    try:
        load_settings(config_dir, env)
    except ConfigurationError as exc:
        return [str(exc)]
    return []


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Process-wide settings (cached). Call ``get_settings.cache_clear()`` in tests."""
    load_dotenv_if_present()
    return load_settings()
