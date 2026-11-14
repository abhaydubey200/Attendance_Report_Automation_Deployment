"""Shared base for contracts."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class SourceSystem(StrEnum):
    BIZOM = "BIZOM"
    POCKET_HRMS = "POCKET_HRMS"
    HR = "HR"


class ContractModel(BaseModel):
    """Immutable, strict contract base: unknown fields are rejected."""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


class SourcedRecord(ContractModel):
    """Every standardized record must be traceable to its source (PRD 5.8)."""

    source_system: SourceSystem
    source_record_id: str | None = Field(default=None, description="Row/record reference within the source upload")
    upload_id: int | None = Field(default=None, description="staging.upload_registry reference (Phase 2)")


def require_aware(value: datetime | None) -> datetime | None:
    """Timestamps must carry a timezone so IST/UTC handling is never ambiguous."""
    if value is not None and value.tzinfo is None:
        raise ValueError("timestamp must be timezone-aware")
    return value
