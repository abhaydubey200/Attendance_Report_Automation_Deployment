"""Dataset registry loaded from config/datasets.yaml (PRD 6.1).

Column definitions are populated only from inspected sample files. A dataset whose
schema_status is PENDING_DISCOVERY cannot pass schema validation.
"""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from contracts.base import SourceSystem
from core.exceptions import ConfigurationError
from core.paths import CONFIG_DIR


class SchemaStatus(StrEnum):
    PENDING_DISCOVERY = "PENDING_DISCOVERY"
    DEFINED = "DEFINED"


class DatasetDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    dataset_id: str = Field(pattern=r"^[A-Z][A-Z0-9_]+$")
    dataset_name: str
    source_system: SourceSystem
    frequency: Literal["DAILY", "AS_UPDATED", "MONTHLY"]
    file_formats: tuple[str, ...]
    active: bool = True
    schema_version: str
    schema_status: SchemaStatus
    required_columns: tuple[str, ...] = ()
    optional_columns: tuple[str, ...] = ()
    column_mappings: dict[str, str] = Field(default_factory=dict)
    primary_key_columns: tuple[str, ...] = ()
    date_column: str | None = None
    validation_rules: tuple[Any, ...] = ()
    seed_schema: dict[str, Any] | None = None   # {"notes": str, "definition": SchemaDefinition dict}

    @model_validator(mode="after")
    def _defined_schema_is_complete(self) -> "DatasetDefinition":
        if self.schema_status is SchemaStatus.DEFINED and not self.required_columns:
            raise ValueError(f"{self.dataset_id}: DEFINED schema must list required_columns")
        known = set(self.required_columns) | set(self.optional_columns)
        unknown_pk = set(self.primary_key_columns) - known
        if unknown_pk:
            raise ValueError(f"{self.dataset_id}: primary key columns not declared: {sorted(unknown_pk)}")
        if self.date_column and self.date_column not in known:
            raise ValueError(f"{self.dataset_id}: date_column {self.date_column!r} not declared")
        return self

    @property
    def ready_for_upload_validation(self) -> bool:
        return self.active and self.schema_status is SchemaStatus.DEFINED


class DatasetRegistry(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    source_systems: dict[SourceSystem, str]
    datasets: tuple[DatasetDefinition, ...]

    @model_validator(mode="after")
    def _unique_ids(self) -> "DatasetRegistry":
        ids = [d.dataset_id for d in self.datasets]
        dupes = {i for i in ids if ids.count(i) > 1}
        if dupes:
            raise ValueError(f"duplicate dataset_id: {sorted(dupes)}")
        return self

    def get(self, dataset_id: str) -> DatasetDefinition:
        for d in self.datasets:
            if d.dataset_id == dataset_id:
                return d
        raise KeyError(dataset_id)

    def active(self) -> list[DatasetDefinition]:
        return [d for d in self.datasets if d.active]


def load_dataset_registry(config_dir: Path | None = None) -> DatasetRegistry:
    import yaml

    path = Path(config_dir or CONFIG_DIR) / "datasets.yaml"
    if not path.is_file():
        raise ConfigurationError(f"Configuration file not found: {path}")
    try:
        return DatasetRegistry.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))
    except (ValidationError, yaml.YAMLError) as exc:
        raise ConfigurationError(f"datasets.yaml: {exc}") from exc
