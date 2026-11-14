"""audit.* tables (PRD 10.3). Append-only by convention; no update/delete paths exist."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from core.timeutils import now_utc
from database.models.base import Base, BigId, UtcDateTime

SCHEMA = "audit"


class UserActivityLog(Base):
    __tablename__ = "user_activity_log"
    __table_args__ = (
        Index("ix_user_activity_log_occurred_at", "occurred_at"),
        Index("ix_user_activity_log_user_id", "user_id"),
        {"schema": SCHEMA},
    )

    activity_id: Mapped[int] = mapped_column(BigId, primary_key=True, autoincrement=True)
    occurred_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False, default=now_utc)
    user_id: Mapped[int | None] = mapped_column(Integer)          # no FK: audit must survive user changes
    username: Mapped[str | None] = mapped_column(String(100))
    action: Mapped[str] = mapped_column(String(50), nullable=False)
    outcome: Mapped[str] = mapped_column(String(20), nullable=False)
    detail: Mapped[str | None] = mapped_column(Text)               # JSON, redacted


class ProcessingLog(Base):
    """Stage-level log for each processing run (PRD 17.3, 21.6)."""

    __tablename__ = "processing_log"
    __table_args__ = (Index("ix_processing_log_run", "run_id"), {"schema": SCHEMA})

    id: Mapped[int] = mapped_column(BigId, primary_key=True, autoincrement=True)
    run_id: Mapped[int] = mapped_column(Integer, nullable=False)
    stage: Mapped[str] = mapped_column(String(30), nullable=False)
    outcome: Mapped[str] = mapped_column(String(20), nullable=False)
    started_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False, default=now_utc)
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    record_count: Mapped[int | None] = mapped_column(Integer)
    message: Mapped[str | None] = mapped_column(String(1000))


class ExceptionResolutionLog(Base):
    __tablename__ = "exception_resolution_log"
    __table_args__ = (Index("ix_exception_resolution_log_exc", "exception_id"), {"schema": SCHEMA})

    id: Mapped[int] = mapped_column(BigId, primary_key=True, autoincrement=True)
    exception_id: Mapped[int] = mapped_column(Integer, nullable=False)
    from_status: Mapped[str] = mapped_column(String(20), nullable=False)
    to_status: Mapped[str] = mapped_column(String(20), nullable=False)
    actor: Mapped[str] = mapped_column(String(100), nullable=False)
    comment: Mapped[str | None] = mapped_column(String(1000))
    occurred_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False, default=now_utc)


class EmailDeliveryLog(Base):
    __tablename__ = "email_delivery_log"
    __table_args__ = (UniqueConstraint("report_id", "recipient"), {"schema": SCHEMA})

    id: Mapped[int] = mapped_column(BigId, primary_key=True, autoincrement=True)
    report_id: Mapped[int] = mapped_column(Integer, nullable=False)
    recipient: Mapped[str] = mapped_column(String(320), nullable=False)
    mode: Mapped[str] = mapped_column(String(10), nullable=False)       # TEST | LIVE
    status: Mapped[str] = mapped_column(String(20), nullable=False)     # SENT | FAILED
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error: Mapped[str | None] = mapped_column(String(500))
    sent_at: Mapped[datetime | None] = mapped_column(UtcDateTime)


class AIExecutionLog(Base):
    __tablename__ = "ai_execution_log"
    __table_args__ = {"schema": SCHEMA}

    id: Mapped[int] = mapped_column(BigId, primary_key=True, autoincrement=True)
    feature: Mapped[str] = mapped_column(String(30), nullable=False)    # SUMMARY | ANALYST
    run_id: Mapped[int | None] = mapped_column(Integer)
    username: Mapped[str | None] = mapped_column(String(100))
    model: Mapped[str | None] = mapped_column(String(100))
    prompt_version: Mapped[str | None] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(20), nullable=False)     # OK | UNAVAILABLE | REJECTED | DISABLED
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    detail: Mapped[str | None] = mapped_column(Text)
    occurred_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False, default=now_utc)
