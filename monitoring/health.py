"""System health checks shared by `python main.py check` and the System Monitoring pages."""

from __future__ import annotations

import sys
import uuid
from dataclasses import dataclass
from enum import StrEnum

from sqlalchemy import Engine

from core.config import Settings, load_attendance_rules, validate_all_configs


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
    return HealthCheck("Configuration", Status.OK, f"all files valid (environment: {settings.environment})")


def check_storage(settings: Settings) -> HealthCheck:
    problems = []
    areas = {**settings.storage.all_areas(), "logs": settings.logging.dir}
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
    return HealthCheck("Storage", Status.OK, f"{len(areas)} locations writable under {settings.storage.base_dir}")


def check_db(engine: Engine | None, settings: Settings) -> HealthCheck:
    from database.connection import check_database
    from database.migrate import head_revision

    if engine is None:
        return HealthCheck("Database", Status.FAIL, "engine could not be created (see configuration)")
    status = check_database(engine, settings)
    if not status.reachable:
        return HealthCheck("Database", Status.FAIL, f"[{status.profile}] {status.detail}")
    head = head_revision()
    if status.schema_revision != head:
        return HealthCheck(
            "Database", Status.WARN,
            f"[{status.profile}] schema at {status.schema_revision or 'none'}, head is {head} -- run: python main.py init-db",
        )
    if status.backend == "sqlite":
        return HealthCheck("Database", Status.WARN, f"[{status.profile}] SQLite development database (not for production)")
    return HealthCheck("Database", Status.OK, f"[{status.profile}] SQL Server, schema {status.schema_revision}")


def check_rules() -> HealthCheck:
    rules = load_attendance_rules()
    unresolved = rules.calculation.unresolved_rules()
    if rules.is_approved:
        return HealthCheck("Attendance rules", Status.OK, f"version {rules.rule_version} approved")
    return HealthCheck(
        "Attendance rules", Status.WARN,
        f"version {rules.rule_version} {rules.approval_status}; {len(unresolved)} HR decisions pending -- calculations would be PROVISIONAL",
    )


def check_ai(settings: Settings) -> HealthCheck:
    if not settings.features.ai_enabled:
        return HealthCheck("AI (optional)", Status.OK, "disabled")
    return HealthCheck("AI (optional)", Status.WARN, f"enabled ({settings.ai.model}); connectivity not checked in Phase 1")


def run_all(settings: Settings, engine: Engine | None) -> list[HealthCheck]:
    return [
        check_python(),
        check_configuration(settings),
        check_storage(settings),
        check_db(engine, settings),
        check_rules(),
        check_ai(settings),
    ]
