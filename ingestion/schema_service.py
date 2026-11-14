"""Versioned dataset schemas stored centrally (PRD 6.1). Saving a new version retires
the previous one; old versions stay for lineage of earlier uploads."""

from __future__ import annotations

import json
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from database.models.staging import DatasetSchema
from ingestion.schema_definition import SchemaDefinition


class SchemaError(ValueError):
    pass


@dataclass(frozen=True)
class ActiveSchema:
    dataset_id: str
    version: int
    definition: SchemaDefinition
    created_by: str
    notes: str | None


def get_active_schema(session: Session, dataset_id: str) -> ActiveSchema | None:
    row = session.scalar(
        select(DatasetSchema).where(DatasetSchema.dataset_id == dataset_id, DatasetSchema.status == "ACTIVE")
        .order_by(DatasetSchema.version.desc())
    )
    if row is None:
        return None
    return ActiveSchema(dataset_id, row.version, SchemaDefinition.model_validate_json(row.definition), row.created_by, row.notes)


def list_versions(session: Session, dataset_id: str) -> list[DatasetSchema]:
    return list(session.scalars(select(DatasetSchema).where(DatasetSchema.dataset_id == dataset_id)
                                .order_by(DatasetSchema.version.desc())))


def save_schema(session: Session, dataset_id: str, definition: SchemaDefinition, actor: str, notes: str | None = None) -> ActiveSchema:
    problems = definition.validate_for(dataset_id)
    if problems:
        raise SchemaError(" ".join(problems))
    current = session.scalar(select(func.max(DatasetSchema.version)).where(DatasetSchema.dataset_id == dataset_id)) or 0
    for row in session.scalars(select(DatasetSchema).where(DatasetSchema.dataset_id == dataset_id, DatasetSchema.status == "ACTIVE")):
        row.status = "RETIRED"
    session.add(DatasetSchema(
        dataset_id=dataset_id, version=current + 1, status="ACTIVE",
        definition=json.dumps(definition.model_dump(), sort_keys=True), notes=notes, created_by=actor,
    ))
    session.flush()
    return ActiveSchema(dataset_id, current + 1, definition, actor, notes)
