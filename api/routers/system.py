"""System monitoring endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import Engine

from api.deps import get_engine, get_settings, require
from api.schemas import DatasetRow, HealthItem, KeyValue, SourceAuthorityRow, SystemConfig
from core.config import Settings, load_attendance_rules, load_source_authority
from ingestion.dataset_registry import load_dataset_registry
from monitoring.health import run_all
from security.permissions import Perm, Principal

router = APIRouter(prefix="/system", tags=["system"])


@router.get("/health", response_model=list[HealthItem])
def health(
    _: Principal = Depends(require(Perm.SYSTEM_MONITOR)),
    settings: Settings = Depends(get_settings),
    engine: Engine = Depends(get_engine),
) -> list[HealthItem]:
    return [HealthItem(name=c.name, status=c.status, detail=c.detail) for c in run_all(settings, engine)]


@router.get("/config", response_model=SystemConfig)
def configuration(
    _: Principal = Depends(require(Perm.SYSTEM_MONITOR)),
    settings: Settings = Depends(get_settings),
) -> SystemConfig:
    rules = load_attendance_rules(settings.config_dir)
    registry = load_dataset_registry(settings.config_dir)
    authority = load_source_authority(settings.config_dir)
    app_rows = [
        ("Environment", settings.environment),
        ("Timezone", settings.app.timezone),
        ("Database profile", f"{settings.database.name} ({settings.database.backend})"),
        ("Max upload size", f"{settings.uploads.max_file_size_mb} MB"),
        ("Allowed extensions", ", ".join(settings.uploads.allowed_extensions)),
        ("Idle timeout", f"{settings.session.idle_timeout_minutes} min"),
        ("Email distribution", "enabled" if settings.features.email_enabled else "disabled"),
        ("AI", "enabled" if settings.features.ai_enabled else "disabled"),
    ]
    return SystemConfig(
        application=[KeyValue(key=k, value=v) for k, v in app_rows],
        datasets=[
            DatasetRow(
                dataset_id=d.dataset_id, dataset_name=d.dataset_name, source_system=d.source_system.value,
                frequency=d.frequency, active=d.active, schema_status=d.schema_status.value,
                columns_defined=len(d.required_columns),
            )
            for d in registry.datasets
        ],
        rule_version=rules.rule_version,
        rule_approval_status=rules.approval_status,
        rules=[
            KeyValue(key=k, value="PENDING HR DECISION" if v is None else str(v))
            for k, v in rules.calculation.model_dump().items()
        ],
        source_authority=[
            SourceAuthorityRow(domain=k, proposed_source=v.proposed_source, authoritative_source=v.authoritative_source)
            for k, v in authority.domains.items()
        ],
    )
