"""audit.* tables (PRD 10.3). Append-only by convention; no update/delete paths exist."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Index, Integer, String, Text
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
