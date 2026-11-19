"""Module 2 settings: counting rules, warning-sign limits and email options. Saved in the shared app_setting table
under their own keys ("sales_rules", "sales_email"), so Module 1's settings are never touched."""

from __future__ import annotations

import json
import re

from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session

from database.models.daily import AppSetting

_TIME = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
_EMAIL = re.compile(r"^[A-Za-z0-9._%+'-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")


class SalesRules(BaseModel):
    # Bizom decides present (by 10:30) / late (10:31-13:59) / halfday (14:00+); these are shown for reference and used
    # only when a row has no Bizom status.
    late_after: str = "10:30"
    half_day_from: str = "14:00"
    not_marked_is_absent: bool = True             # active staff missing from the attendance file = absent
    include_promoters: bool = False               # AP... codes / designation Promoter
    promoter_codes: list[str] = Field(default_factory=lambda: ["^AP"])
    # The staff import takes only these codes: HR's Employee Amendment file holds the whole company (HO / RK / NA are
    # Module 1's people and must never become field sales staff).
    staff_codes: list[str] = Field(default_factory=lambda: ["^SL"])
    exclude_codes: list[str] = Field(default_factory=lambda: ["^VACANT", "^TEST"])
    # warning signs ("needs checking")
    # Supervisors rarely transact themselves (18-Nov: 34 of 39 ASE, 18 of 19 ASM, all RSM had no transaction), so the
    # market-activity checks apply to field roles only.
    supervisor_designations: list[str] = Field(default_factory=lambda: ["ASE", "ASM", "SR. ASM", "TSM", "RSM", "DRSM", "ZSM", "NSM",
                                                                         "KAM", "RM", "AM"])
    short_market_minutes: int = 240               # in market under 4 h
    very_short_market_minutes: int = 60
    late_start_minutes: int = 240                 # first activity 4 h+ after marking attendance
    high_km: float = 200.0
    attendance_far_m: float = 50.0
    short_day_minutes: int = 240                  # attendance to end-of-day under 4 h
    short_call_seconds: int = 60
    short_calls_min: int = 3                      # at least this many short calls AND half of all calls
    far_call_m: float = 100.0
    max_speed_kmh: float = 60.0
    calls_after: str = "20:00"
    beat_jump_min: int = 3

    @field_validator("late_after", "half_day_from", "calls_after")
    @classmethod
    def _t(cls, v: str) -> str:
        if not _TIME.match(v):
            raise ValueError("Use 24-hour HH:MM.")
        return v


class SalesEmail(BaseModel):
    mode: str = "test"                             # test = saved to the outbox, never sent | live
    approval_required: bool = True
    test_recipient: str | None = None              # testing: every email goes here instead
    director_name: str = "Director"
    director_emails: list[str] = Field(default_factory=list)
    hr_emails: list[str] = Field(default_factory=list)
    always_bcc: list[str] = Field(default_factory=list)
    levels: list[str] = Field(default_factory=lambda: ["manager", "asm", "zonal", "hod"])   # who gets a team email
    attach_excel: bool = True
    attach_dashboard: bool = True

    @field_validator("mode")
    @classmethod
    def _m(cls, v: str) -> str:
        if v not in ("test", "live"):
            raise ValueError("mode must be test or live.")
        return v

    @field_validator("director_emails", "hr_emails", "always_bcc")
    @classmethod
    def _e(cls, v: list[str]) -> list[str]:
        out = [a.strip().lower() for a in v if a.strip()]
        bad = [a for a in out if not _EMAIL.match(a)]
        if bad:
            raise ValueError(f"Not an email address: {', '.join(bad)}")
        return out

    @field_validator("test_recipient")
    @classmethod
    def _t(cls, v: str | None) -> str | None:
        v = (v or "").strip().lower() or None
        if v and not _EMAIL.match(v):
            raise ValueError("Not an email address.")
        return v

    @field_validator("levels")
    @classmethod
    def _l(cls, v: list[str]) -> list[str]:
        bad = [x for x in v if x not in ("manager", "asm", "zonal", "hod")]
        if bad:
            raise ValueError(f"Unknown level: {', '.join(bad)}")
        return v


def _get(session: Session, key: str) -> dict:
    row = session.get(AppSetting, key)
    return json.loads(row.value) if row else {}


def _put(session: Session, key: str, value: dict, actor: str) -> None:
    row = session.get(AppSetting, key) or AppSetting(key=key)
    row.value, row.updated_by = json.dumps(value), actor
    session.add(row)
    session.flush()


def get_rules(session: Session) -> SalesRules:
    saved = _get(session, "sales_rules")
    return SalesRules.model_validate({k: v for k, v in saved.items() if k in SalesRules.model_fields})


def save_rules(session: Session, rules: SalesRules, actor: str) -> SalesRules:
    _put(session, "sales_rules", rules.model_dump(), actor)
    return rules


def get_email(session: Session) -> SalesEmail:
    saved = _get(session, "sales_email")
    return SalesEmail.model_validate({k: v for k, v in saved.items() if k in SalesEmail.model_fields})


def save_email(session: Session, email: SalesEmail, actor: str) -> SalesEmail:
    _put(session, "sales_email", email.model_dump(), actor)
    return email


def valid_email(v: str | None) -> bool:
    return bool(v and _EMAIL.match(v.strip()))
