"""reporting.* -- generated reports, approvals, AI summaries (PRD 11, 13, 14)."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from core.timeutils import now_utc
from database.models.base import Base, UtcDateTime

SCHEMA = "reporting"


class ReportRegistry(Base):
    __tablename__ = "report_registry"
    __table_args__ = (Index("ix_report_registry_run", "run_id"), {"schema": SCHEMA})

    report_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("attendance.processing_run.run_id"), nullable=False)
    report_type: Mapped[str] = mapped_column(String(20), nullable=False)    # HOD | DIRECTORS | HR_ADMIN
    department_code: Mapped[str | None] = mapped_column(String(50))
    file_format: Mapped[str] = mapped_column(String(10), nullable=False)    # XLSX | HTML
    report_version: Mapped[int] = mapped_column(Integer, nullable=False)
    file_path: Mapped[str] = mapped_column(String(500), nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    provisional: Mapped[bool] = mapped_column(Boolean, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)         # GENERATED | APPROVED | REJECTED | DISTRIBUTED
    generated_by: Mapped[str] = mapped_column(String(100), nullable=False)
    generated_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False, default=now_utc)


class ReportApproval(Base):
    __tablename__ = "report_approval"
    __table_args__ = {"schema": SCHEMA}

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    report_id: Mapped[int] = mapped_column(ForeignKey(f"{SCHEMA}.report_registry.report_id"), nullable=False)
    decision: Mapped[str] = mapped_column(String(20), nullable=False)       # APPROVED | REJECTED
    actor: Mapped[str] = mapped_column(String(100), nullable=False)
    comment: Mapped[str | None] = mapped_column(String(1000))
    decided_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False, default=now_utc)


class AISummary(Base):
    __tablename__ = "ai_summary"
    __table_args__ = (Index("ix_ai_summary_run", "run_id"), {"schema": SCHEMA})

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("attendance.processing_run.run_id"), nullable=False)
    scope: Mapped[str] = mapped_column(String(60), nullable=False)          # ORG | DEPT:<code>
    status: Mapped[str] = mapped_column(String(20), nullable=False)         # GENERATED | UNAVAILABLE | REJECTED
    summary: Mapped[str | None] = mapped_column(Text)
    context: Mapped[str] = mapped_column(Text, nullable=False)              # JSON metrics the text may use
    model: Mapped[str | None] = mapped_column(String(100))
    prompt_version: Mapped[str] = mapped_column(String(20), nullable=False)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False, default=now_utc)
