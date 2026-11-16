"""Counting rules and email options edited in the Settings screen.

Values saved in the database override the defaults in config/settings.yaml.
"""

from __future__ import annotations

import json
import re

from sqlalchemy.orm import Session

from core.config import EmailSettings, Rules, Settings
from database.models.daily import AppSetting

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
    if not saved:
        return settings.rules
    known = set(Rules.model_fields)          # settings saved by older versions may hold retired keys
    return Rules.model_validate({**settings.rules.model_dump(), **{k: v for k, v in saved.items() if k in known}})


def save_rules(session: Session, rules: Rules, actor: str) -> Rules:
    _put(session, "rules", rules.model_dump(), actor)
    return rules


def get_email_settings(session: Session, settings: Settings) -> EmailSettings:
    saved = _get(session, "email")
    if not saved:
        return settings.email
    known = set(EmailSettings.model_fields)
    return EmailSettings.model_validate({**settings.email.model_dump(), **{k: v for k, v in saved.items() if k in known}})


def save_email_settings(session: Session, email: EmailSettings, actor: str) -> EmailSettings:
    _put(session, "email", email.model_dump(), actor)
    return email


def valid_email(address: str) -> bool:
    return bool(_EMAIL.match(address.strip()))
