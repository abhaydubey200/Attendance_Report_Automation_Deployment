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
    # ... except before their date of joining, and on a company off day: Bizom never records Sundays / holidays as off
    # (6 months of data: 91% of staff "not marked" on every Sunday, and on 15-Aug, 2-Oct, 20-Oct ...). On such a day the
    # people who did not mark are counted as week off / holiday, not absent; those who worked are still present.
    sunday_off: bool = True
    off_day_below: float = 0.40                   # fewer than this share marked: looks like a holiday - HR confirms it
    holidays: dict[str, str] = Field(default_factory=dict)       # HR's field-sales holiday calendar: "YYYY-MM-DD" -> name
    working_days: list[str] = Field(default_factory=list)        # days HR confirmed as working days (also a Sunday worked)
    include_promoters: bool = False               # AP... codes / designation Promoter
    promoter_codes: list[str] = Field(default_factory=lambda: ["^AP"])
    # The staff import takes only these codes: HR's Employee Amendment file holds the whole company (HO / RK / NA are
    # Module 1's people and must never become field sales staff).
    staff_codes: list[str] = Field(default_factory=lambda: ["^SL"])
    exclude_codes: list[str] = Field(default_factory=lambda: ["^VACANT", "^TEST"])
    # warning signs ("needs checking")
    # Supervisors rarely transact themselves (18-Nov: 34 of 39 ASE, 18 of 19 ASM, all RSM had no transaction), so the
    # market-activity checks apply to field roles only.
    # 6 months (May-Nov 2026): key-account and some other roles also rarely transact in Bizom - 'no market activity' on 56% of
    # KAE days, 91% of SE days, 37% of Sales Representative days (SO 8%, SR 5%) - so the sign says nothing for them.
    supervisor_designations: list[str] = Field(default_factory=lambda: ["ASE", "ASM", "SR. ASM", "TSM", "RSM", "DRSM", "ZSM", "NSM",
                                                                         "KAM", "RM", "AM", "KAE", "SE", "SALES REPRESENTATIVE"])
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
    # location checks (sales.geo) - shown in the app; in emails only once geo_in_emails is switched on
    geo_in_emails: bool = True                    # 2026-11-21: the user asked for the checks in the emails
    keep_months: int = 12                         # locations, photo links and phone codes are deleted after this (12 since 2026-11-22: training)
    geo_away_outlet_m: float = 300.0              # call made this far from the outlet's own location
    geo_away_outlet_min: int = 2                  # ... on at least this many calls
    geo_same_spot_m: float = 100.0                # all calls within this distance of their middle point
    geo_same_spot_min_calls: int = 5
    geo_cluster_m: float = 50.0                   # several outlets "visited" from one spot
    geo_cluster_outlets: int = 3
    geo_cluster_outlet_far_m: float = 200.0       # ... while those outlets are this far from that spot
    geo_km_ratio: float = 2.0                     # Bizom KM more than this many times the route between the day's points
    geo_km_extra: float = 30.0                    # ... and at least this many km more
    geo_start_away_km: float = 10.0               # attendance this far from the person's usual start point
    geo_start_history_days: int = 30
    geo_start_min_days: int = 5                   # need this many earlier days to know the usual start point
    geo_end_away_km: float = 25.0                 # day ended this far from the last call
    geo_offbeat_min: int = 3                      # calls outside the day's main beat
    geo_together_m: float = 200.0                 # two people's calls this close ...
    geo_together_minutes: int = 15                # ... within this many minutes ...
    geo_together_share: float = 0.6               # ... for this share of the person's calls
    geo_together_min_calls: int = 4
    # photo checks (sales.photos): selfies are downloaded from Bizom's image server, fingerprinted in memory, never stored
    photo_downloads: bool = True
    photo_batch: int = 3000                       # photos fetched per run (daily job / "Check photos now")
    # "nearly identical" = perceptual-hash bits that may differ. Measured on 14,545 real selfies (2026-11-21): between different
    # people, chance alone gives ~265 matches at 6 bits and ~0 at 4; for one person on different days, real reuse shows at 0-2 bits.
    photo_same_bits: int = 4                      # another person's selfie
    photo_reuse_bits: int = 2                     # the same person's selfie from another day
    # look-alike pairs are confirmed by comparing image details (ORB + RANSAC). Measured 2026-11-22: real reuse 73-126
    # matching details, different photos 0-12 (a same-wall background up to ~68 in one control pair).
    photo_confirm_points: int = 70
    # warning signs switched off after the calibration review showed they are wrong most of the time
    disabled_signs: list[str] = Field(default_factory=list)
    odd_hour_before: str = "07:00"                # attendance marked before this ...
    odd_hour_after: str = "20:00"                 # ... or at / after this is an odd hour
    gps_frozen_days: int = 4                      # the exact same GPS point (to ~10 cm) on this many earlier days (last 30)
    photo_dark: float = 40.0                      # average brightness (0-255) below this = too dark
    photo_blurry: float = 15.0                    # sharpness below this = too blurry to judge
    photo_time_hours: float = 2.0                 # time written in the photo this far from the attendance time
    # selfie taken this many minutes or more BEFORE the attendance mark (same day, under photo_time_hours): 98.6% of dated
    # selfies are within a minute of it, 0.3% are 15+ minutes older (78k selfies, May-Nov 2026)
    photo_early_minutes: float = 15.0

    @field_validator("late_after", "half_day_from", "calls_after")
    @classmethod
    def _t(cls, v: str) -> str:
        if not _TIME.match(v):
            raise ValueError("Use 24-hour HH:MM.")
        return v


class SalesEmail(BaseModel):
    mode: str = "test"                             # test = saved to the outbox, never sent | live
    approval_required: bool = True
    auto_send: bool = False                        # daily job: send the prepared emails without waiting for Approve
    test_recipient: str | None = None              # testing: every email really goes ONLY here (To), marked [TEST]
    test_cc: list[str] = Field(default_factory=list)  # testing: CC on every test email
    director_email: bool = True                    # Director gets the company summary (off = not prepared at all)
    hr_email: bool = True                          # HR gets the exception email (off = not prepared at all)
    director_name: str = "Director"
    director_emails: list[str] = Field(default_factory=list)
    hr_emails: list[str] = Field(default_factory=list)
    always_bcc: list[str] = Field(default_factory=list)
    # pilot: while the mode is "test", emails to these addresses only are really sent (everyone else: outbox only)
    pilot_live: list[str] = Field(default_factory=list)
    levels: list[str] = Field(default_factory=lambda: ["manager", "asm", "zonal", "hod"])   # who gets a team email
    attach_excel: bool = True
    attach_dashboard: bool = True

    @field_validator("mode")
    @classmethod
    def _m(cls, v: str) -> str:
        if v not in ("test", "live"):
            raise ValueError("mode must be test or live.")
        return v

    @field_validator("director_emails", "hr_emails", "always_bcc", "pilot_live", "test_cc")
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
