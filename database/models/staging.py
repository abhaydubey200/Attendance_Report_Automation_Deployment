"""staging.* -- raw upload layer (PRD 5.7, 5.8, 6.1, 10.3)."""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Boolean, Date, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from core.timeutils import now_utc
from database.models.base import Base, BigId, UtcDateTime

SCHEMA = "staging"


class DatasetSchema(Base):
    """Versioned column definition for a dataset, created from an inspected sample file."""

    __tablename__ = "dataset_schema"
    __table_args__ = (UniqueConstraint("dataset_id", "version"), {"schema": SCHEMA})

    schema_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    dataset_id: Mapped[str] = mapped_column(String(50), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)  # ACTIVE | RETIRED
    definition: Mapped[str] = mapped_column(Text, nullable=False)    # JSON
    notes: Mapped[str | None] = mapped_column(String(500))
    created_by: Mapped[str] = mapped_column(String(100), nullable=False)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False, default=now_utc)


class UploadRegistry(Base):
    __tablename__ = "upload_registry"
    __table_args__ = (
        Index("ix_upload_registry_sha256", "sha256"),
        Index("ix_upload_registry_dataset_date", "dataset_id", "reporting_date"),
        {"schema": SCHEMA},
    )

    upload_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    dataset_id: Mapped[str] = mapped_column(String(50), nullable=False)
    source_system: Mapped[str] = mapped_column(String(20), nullable=False)
    reporting_date: Mapped[date] = mapped_column(Date, nullable=False)
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    stored_path: Mapped[str] = mapped_column(String(500), nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    file_type: Mapped[str] = mapped_column(String(10), nullable=False)
    sheet_name: Mapped[str | None] = mapped_column(String(100))
    header_row: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    schema_version: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    validation_status: Mapped[str] = mapped_column(String(20), nullable=False)  # VALID | REQUIRES_REVIEW | REJECTED
    total_rows: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    valid_rows: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    invalid_rows: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    duplicate_rows: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    warning_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    standardized_rows: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_current: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    reprocess_of: Mapped[int | None] = mapped_column(ForeignKey(f"{SCHEMA}.upload_registry.upload_id"))
    superseded_by: Mapped[int | None] = mapped_column(Integer)
    uploaded_by: Mapped[str] = mapped_column(String(100), nullable=False)
    uploaded_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False, default=now_utc)


class UploadRow(Base):
    """Raw rows exactly as read (strings), kept for lineage and reprocessing."""

    __tablename__ = "upload_row"
    __table_args__ = {"schema": SCHEMA}

    upload_id: Mapped[int] = mapped_column(ForeignKey(f"{SCHEMA}.upload_registry.upload_id"), primary_key=True)
    row_number: Mapped[int] = mapped_column(Integer, primary_key=True)
    data: Mapped[str] = mapped_column(Text, nullable=False)  # JSON object column -> raw string
    is_valid: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class ValidationIssue(Base):
    __tablename__ = "validation_issue"
    __table_args__ = (Index("ix_validation_issue_upload_id", "upload_id"), {"schema": SCHEMA})

    issue_id: Mapped[int] = mapped_column(BigId, primary_key=True, autoincrement=True)
    upload_id: Mapped[int] = mapped_column(ForeignKey(f"{SCHEMA}.upload_registry.upload_id"), nullable=False)
    row_number: Mapped[int | None] = mapped_column(Integer)
    column_name: Mapped[str | None] = mapped_column(String(200))
    code: Mapped[str] = mapped_column(String(50), nullable=False)
    severity: Mapped[str] = mapped_column(String(10), nullable=False)  # ERROR | WARNING
    message: Mapped[str] = mapped_column(String(500), nullable=False)
