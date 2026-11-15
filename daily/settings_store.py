"""Counting rules, email options and recipients edited in the Settings screen.

Values saved in the database override the defaults in config/settings.yaml.
"""

from __future__ import annotations

import json
import re

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from core.config import EmailSettings, Rules, Settings
from database.models.daily import AppSetting, Recipient

ALL = "ALL"
_EMAIL = re.compile(r"^[A-Za-z0-9._%+'-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")


def _get(session: Session, key: str) -> dict | None:
    row = session.get(AppSetting, key)
    return json.loads(row.value) if row else None


def _put(session: Session, key: str, value: dict, actor: str) -> None:
    row = session.get(AppSetting, key) or AppSetting(key=key)
    row.value, row.updated_by = json.dumps(value), actor
    session.add(row)
    session.flush()


def get_rules(session: Session, settings: Settings) -> Rules:
    saved = _get(session, "rules")
    return Rules.model_validate({**settings.rules.model_dump(), **saved}) if saved else settings.rules


def save_rules(session: Session, rules: Rules, actor: str) -> Rules:
    _put(session, "rules", rules.model_dump(), actor)
    return rules


def get_email_settings(session: Session, settings: Settings) -> EmailSettings:
    saved = _get(session, "email")
    return EmailSettings.model_validate({**settings.email.model_dump(), **saved}) if saved else settings.email


def save_email_settings(session: Session, email: EmailSettings, actor: str) -> EmailSettings:
    _put(session, "email", email.model_dump(), actor)
    return email


def valid_email(address: str) -> bool:
    return bool(_EMAIL.match(address.strip()))


def list_recipients(session: Session) -> list[Recipient]:
    return list(session.scalars(select(Recipient).order_by(Recipient.scope, Recipient.name)))


def replace_recipients(session: Session, rows: list[dict]) -> list[Recipient]:
    """Replace the whole list (the Settings screen edits it as one table)."""
    seen: set[tuple[str, str]] = set()
    clean = []
    for r in rows:
        name, email, scope = (r.get("name") or "").strip(), (r.get("email") or "").strip(), (r.get("scope") or "").strip()
        if not email and not name:
            continue
        if not valid_email(email):
            raise ValueError(f"Invalid email address: {email or '(empty)'}")
        if not scope:
            raise ValueError(f"Choose who {email} should receive reports for.")
        key = (email.lower(), scope.upper())
        if key in seen:
            continue
        seen.add(key)
        clean.append(Recipient(name=name or email, email=email, scope=ALL if scope.upper() == ALL else scope,
                               active=bool(r.get("active", True))))
    session.execute(delete(Recipient))
    session.add_all(clean)
    session.flush()
    return clean


def recipients_by_scope(session: Session) -> dict[str, list[Recipient]]:
    out: dict[str, list[Recipient]] = {}
    for r in list_recipients(session):
        if r.active:
            out.setdefault(ALL if r.scope.upper() == ALL else r.scope.strip().lower(), []).append(r)
    return out
