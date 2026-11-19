"""Small Module 2 helpers."""

from __future__ import annotations

from datetime import datetime, timezone


def utc_iso(dt: datetime | None) -> str | None:
    """Stored times are UTC; SQLite gives them back without a zone. Mark them UTC so browsers show the right IST time."""
    if dt is None:
        return None
    return (dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)).isoformat()
