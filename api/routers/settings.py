"""Settings: counting rules and email (Gmail sender, routing switches). Changes are audited."""

from __future__ import annotations

import json
import os

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from api.deps import get_db, get_settings, require
from core.config import EmailSettings, Rules, Settings
from daily.mailer import GMAIL_SECRETS, MailError, build_message, send
from daily.settings_store import get_email_settings, get_rules, save_email_settings, save_rules, valid_email
from database.models.daily import DayUpload
from security.audit import record_activity
from security.permissions import Perm, Principal

router = APIRouter(prefix="/settings", tags=["settings"])


def _known_categories(db: Session) -> list[str]:
    cats: set[str] = set()
    for (insights,) in db.execute(select(DayUpload.insights).where(DayUpload.is_current.is_(True))
                                  .order_by(DayUpload.report_date.desc()).limit(30)):
        cats.update(json.loads(insights).get("categories", []))
    return sorted(cats)


@router.get("")
def get_all(_: Principal = Depends(require(Perm.MANAGE_SETTINGS)), settings: Settings = Depends(get_settings),
            db: Session = Depends(get_db)) -> dict:
    return {
        "rules": get_rules(db, settings).model_dump(),
        "email": get_email_settings(db, settings).model_dump(),
        "secrets": {name: bool(os.environ.get(name)) for name in GMAIL_SECRETS},
        "categories": _known_categories(db),
        "public_url": settings.app.public_url,
    }


def _bad(exc: Exception) -> HTTPException:
    msg = exc.errors()[0]["msg"] if isinstance(exc, ValidationError) else str(exc)
    return HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, msg)


@router.put("/rules")
def put_rules(body: dict, principal: Principal = Depends(require(Perm.MANAGE_SETTINGS)), db: Session = Depends(get_db)) -> dict:
    try:
        rules = Rules.model_validate(body)
    except ValidationError as exc:
        raise _bad(exc) from None
    save_rules(db, rules, principal.username)
    record_activity(db, "SETTINGS_RULES", "SUCCESS", username=principal.username, detail=rules.model_dump())
    return rules.model_dump()


@router.put("/email")
def put_email(body: dict, principal: Principal = Depends(require(Perm.MANAGE_SETTINGS)), db: Session = Depends(get_db)) -> dict:
    try:
        cfg = EmailSettings.model_validate(body)
        cfg.director_emails = [a.strip().lower() for a in cfg.director_emails if a.strip()]
        cfg.hr_emails = [a.strip().lower() for a in cfg.hr_emails if a.strip()]
        cfg.always_cc = list(dict.fromkeys(a.strip().lower() for a in cfg.always_cc if a.strip()))
        cfg.test_recipient = (cfg.test_recipient or "").strip().lower() or None
        cfg.test_cc = [a.strip().lower() for a in cfg.test_cc if a.strip()] if cfg.test_recipient else []
        for label, addrs in (("Test address", [cfg.test_recipient] if cfg.test_recipient else []), ("Test CC", cfg.test_cc),
                             ("Sender", [cfg.sender] if cfg.sender else []), ("Reply-to", [cfg.reply_to] if cfg.reply_to else []),
                             ("Director", cfg.director_emails), ("HR mailbox", cfg.hr_emails), ("Always CC", cfg.always_cc)):
            bad = [a for a in addrs if not valid_email(a)]
            if bad:
                raise ValueError(f"{label} is not a valid email address: {', '.join(bad)}")
        if cfg.mode == "live" and not cfg.sender:
            raise ValueError("Live mode needs the sender mailbox.")
    except (ValidationError, ValueError) as exc:
        raise _bad(exc) from None
    save_email_settings(db, cfg, principal.username)
    record_activity(db, "SETTINGS_EMAIL", "SUCCESS", username=principal.username, detail=cfg.model_dump())
    return cfg.model_dump()


class TestEmailIn(BaseModel):
    to: str


@router.post("/test-email")
def test_email(body: TestEmailIn, principal: Principal = Depends(require(Perm.MANAGE_SETTINGS)),
               settings: Settings = Depends(get_settings), db: Session = Depends(get_db)) -> dict:
    if not valid_email(body.to):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Not a valid email address.")
    cfg = get_email_settings(db, settings)
    msg = build_message(cfg.sender or "apis-attendance@localhost", [body.to], f"{cfg.subject_prefix} - test email",
                        "<p>This is a test email from the APIS Daily Attendance tool. Email delivery works.</p>",
                        "This is a test email from the APIS Daily Attendance tool. Email delivery works.", [])
    try:
        result = send(cfg, msg, settings.storage.area("outbox") / "tests")
    except MailError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from None
    record_activity(db, "TEST_EMAIL", result.status, username=principal.username, detail={"to": body.to, "mode": cfg.mode})
    return {"status": result.status, "mode": cfg.mode}
