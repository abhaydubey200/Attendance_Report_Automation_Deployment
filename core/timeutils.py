"""Timezone helpers. Storage is UTC; display and business dates are IST (PRD: Asia/Kolkata)."""

from __future__ import annotations

from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def now_ist() -> datetime:
    return datetime.now(IST)


def today_ist() -> date:
    return now_ist().date()


def ensure_utc(value: datetime | None) -> datetime | None:
    """Normalise a datetime to aware UTC. Naive values are assumed to already be UTC
    (this is how SQLite returns values written by this application)."""
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def to_ist(value: datetime | None) -> datetime | None:
    utc = ensure_utc(value)
    return utc.astimezone(IST) if utc else None
