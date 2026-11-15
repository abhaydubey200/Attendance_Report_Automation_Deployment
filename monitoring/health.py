"""Health checks for `python main.py check`."""

from __future__ import annotations

import os
import sys
import uuid
from dataclasses import dataclass
from enum import StrEnum

from sqlalchemy import Engine

from core.config import Settings, validate_all_configs


class Status(StrEnum):
    OK = "OK"
    WARN = "WARN"
    FAIL = "FAIL"


@dataclass(frozen=True)
class HealthCheck:
    name: str
    status: Status
    detail: str


def check_python() -> HealthCheck:
    ok = sys.version_info[:2] == (3, 12)
    return HealthCheck("Python runtime", Status.OK if ok else Status.WARN, sys.version.split()[0] + ("" if ok else " (3.12 expected)"))


def check_configuration(settings: Settings) -> HealthCheck:
    errors = validate_all_configs(settings.config_dir)
    if errors:
        return HealthCheck("Configuration", Status.FAIL, "; ".join(errors))
    return HealthCheck("Configuration", Status.OK, f"valid (environment: {settings.environment})")


def check_storage(settings: Settings) -> HealthCheck:
    problems = []
    areas = {"storage": settings.storage.base_dir, "logs": settings.logging.dir}
    for name, path in areas.items():
        try:
            path.mkdir(parents=True, exist_ok=True)
            probe = path / f".write_probe_{uuid.uuid4().hex}"
            probe.write_bytes(b"")
            probe.unlink()
        except OSError as exc:
            problems.append(f"{name}: {type(exc).__name__}")
    if problems:
        return HealthCheck("Storage", Status.FAIL, "not writable -> " + ", ".join(problems))
    return HealthCheck("Storage", Status.OK, f"writable: {settings.storage.base_dir}")


def check_db(engine: Engine | None, settings: Settings) -> HealthCheck:
    from database.connection import check_database
    from database.migrate import head_revision

    if engine is None:
        return HealthCheck("Database", Status.FAIL, "engine could not be created (see configuration)")
    status = check_database(engine, settings)
    if not status.reachable:
        return HealthCheck("Database", Status.FAIL, f"[{status.profile}] {status.detail}")
    if status.schema_revision != head_revision():
        return HealthCheck("Database", Status.WARN, f"[{status.profile}] tables not up to date -- run: python main.py init-db")
    if status.backend == "sqlite":
        return HealthCheck("Database", Status.OK, f"[{status.profile}] SQLite (fine for a single PC; SQL Server for a shared server)")
    return HealthCheck("Database", Status.OK, f"[{status.profile}] SQL Server")


def check_email(settings: Settings, engine: Engine | None) -> HealthCheck:
    cfg = settings.email
    if engine is not None:
        try:
            from database.connection import session_scope
            from daily.settings_store import get_email_settings

            with session_scope(engine) as s:
                cfg = get_email_settings(s, settings)
        except Exception:  # tables may not exist yet
            pass
    if cfg.mode == "test":
        return HealthCheck("Email", Status.WARN, "test mode: emails are saved to the outbox, not sent")
    if not (cfg.smtp_host and cfg.sender):
        return HealthCheck("Email", Status.FAIL, "live mode without SMTP server/sender")
    if cfg.smtp_username and not os.environ.get("SMTP_PASSWORD"):
        return HealthCheck("Email", Status.FAIL, "SMTP_PASSWORD is not set")
    return HealthCheck("Email", Status.OK, f"live via {cfg.smtp_host}:{cfg.smtp_port} as {cfg.sender}")


def run_all(settings: Settings, engine: Engine | None) -> list[HealthCheck]:
    return [check_python(), check_configuration(settings), check_storage(settings), check_db(engine, settings),
            check_email(settings, engine)]
