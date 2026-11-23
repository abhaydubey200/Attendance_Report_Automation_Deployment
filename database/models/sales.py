"""Tables of Module 2 - Field Sales attendance (Bizom). Separate from Module 1 (Head Office, Pocket HRMS) tables.

Location checks (2026-11-21): attendance / day-end / call / outlet coordinates, attendance photo links and a scrambled phone
code ARE stored, for 6 months (then deleted by sales.geo.purge). Phone numbers, outlet mobiles and raw IMEI are never stored.
"""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Boolean, Date, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from core.timeutils import now_utc
from database.models.base import Base, BigId, UtcDateTime

SCHEMA = "daily"


class SalesEmployee(Base):
    """Field sales staff list (from HR): who should mark attendance in Bizom, and who their managers are."""
    __tablename__ = "sales_employee"
    __table_args__ = {"schema": SCHEMA}

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(30), nullable=False, unique=True)         # EMP_CODE, upper case
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    designation: Mapped[str | None] = mapped_column(String(60))
    zone: Mapped[str | None] = mapped_column(String(60))
    hq: Mapped[str | None] = mapped_column(String(100))
    channel: Mapped[str | None] = mapped_column(String(100))                           # e.g. General Trade
    manager_name: Mapped[str | None] = mapped_column(String(200))                      # immediate manager (ASE / TSM / ASM)
    manager_email: Mapped[str | None] = mapped_column(String(200))
    asm_name: Mapped[str | None] = mapped_column(String(200))                          # ASM / RSM
    asm_email: Mapped[str | None] = mapped_column(String(200))
    zonal_name: Mapped[str | None] = mapped_column(String(200))                        # zonal / regional head
    zonal_email: Mapped[str | None] = mapped_column(String(200))
    hod_name: Mapped[str | None] = mapped_column(String(200))
    hod_email: Mapped[str | None] = mapped_column(String(200))
    date_of_joining: Mapped[date | None] = mapped_column(Date)
    holiday_state: Mapped[str | None] = mapped_column(String(40))                      # which page of HR's holiday list applies
    holiday_state_by: Mapped[str | None] = mapped_column(String(120))                  # who confirmed it (HR / GPS suggestion accepted)
    status: Mapped[str] = mapped_column(String(10), nullable=False, default="ACTIVE")  # ACTIVE | LEFT
    exit_date: Mapped[date | None] = mapped_column(Date)
    source: Mapped[str | None] = mapped_column(String(100))
    updated_by: Mapped[str | None] = mapped_column(String(100))
    updated_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False, default=now_utc, onupdate=now_utc)


class SalesDayUpload(Base):
    """One processed Bizom day (attendance report, plus optional EOD and call reports)."""
    __tablename__ = "sales_day_upload"
    __table_args__ = (Index("ix_sales_day_upload_date", "report_date", "is_current"), {"schema": SCHEMA})

    upload_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    report_date: Mapped[date] = mapped_column(Date, nullable=False)
    is_current: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    attendance_file: Mapped[str | None] = mapped_column(String(255))
    eod_file: Mapped[str | None] = mapped_column(String(255))
    calls_file: Mapped[str | None] = mapped_column(String(255))
    sha256: Mapped[str | None] = mapped_column(String(200))                            # of each file, comma separated
    people: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    summary: Mapped[str] = mapped_column(Text, nullable=False)                         # JSON: counts, warnings, data notes
    uploaded_by: Mapped[str] = mapped_column(String(100), nullable=False)
    uploaded_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False, default=now_utc)


class SalesEmployeeDay(Base):
    """One person's day: status, field-work times and the warning signs ("needs checking")."""
    __tablename__ = "sales_employee_day"
    __table_args__ = (Index("ix_sales_employee_day_upload", "upload_id"), Index("ix_sales_employee_day_code", "code"),
                      {"schema": SCHEMA})

    id: Mapped[int] = mapped_column(BigId, primary_key=True, autoincrement=True)
    upload_id: Mapped[int] = mapped_column(ForeignKey(f"{SCHEMA}.sales_day_upload.upload_id"), nullable=False)
    code: Mapped[str] = mapped_column(String(30), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    designation: Mapped[str | None] = mapped_column(String(60))
    zone: Mapped[str | None] = mapped_column(String(60))
    manager_name: Mapped[str | None] = mapped_column(String(200))
    zonal_name: Mapped[str | None] = mapped_column(String(200))
    hod_name: Mapped[str | None] = mapped_column(String(200))
    in_master: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    status: Mapped[str] = mapped_column(String(12), nullable=False)    # PRESENT LATE HALF_DAY LEAVE WEEK_OFF ABSENT
    bizom_status: Mapped[str | None] = mapped_column(String(20))
    leave_type: Mapped[str | None] = mapped_column(String(40))
    attendance_time: Mapped[str | None] = mapped_column(String(8))                     # HH:MM (24 h)
    first_activity: Mapped[str | None] = mapped_column(String(8))
    last_activity: Mapped[str | None] = mapped_column(String(8))
    market_minutes: Mapped[int | None] = mapped_column(Integer)
    km: Mapped[float | None] = mapped_column(Float)
    eod_time: Mapped[str | None] = mapped_column(String(8))
    attendance_variance_m: Mapped[float | None] = mapped_column(Float)
    photo: Mapped[bool | None] = mapped_column(Boolean)
    calls: Mapped[int | None] = mapped_column(Integer)
    productive_calls: Mapped[int | None] = mapped_column(Integer)
    short_calls: Mapped[int | None] = mapped_column(Integer)
    telephonic_calls: Mapped[int | None] = mapped_column(Integer)
    beat_jump_calls: Mapped[int | None] = mapped_column(Integer)
    far_calls: Mapped[int | None] = mapped_column(Integer)
    max_call_distance_m: Mapped[float | None] = mapped_column(Float)
    fast_moves: Mapped[int | None] = mapped_column(Integer)
    order_value: Mapped[float | None] = mapped_column(Float)
    flags: Mapped[str | None] = mapped_column(String(300))                             # comma-separated warning codes
    geo_flags: Mapped[str | None] = mapped_column(String(300))                         # location warning codes (app only for now)
    geo_evidence: Mapped[str | None] = mapped_column(Text)                             # JSON {code: "why, with distances"}
    photo_url: Mapped[str | None] = mapped_column(String(500))                         # attendance selfie link (6 months)
    present_type: Mapped[str | None] = mapped_column(String(40))                       # Bizom Present_Type (HQ / EX-HQ work)


class SalesMailItem(Base):
    """One planned / sent Field Sales email (also the send log)."""
    __tablename__ = "sales_mail_item"
    __table_args__ = (Index("ix_sales_mail_item_date", "report_date"), {"schema": SCHEMA})

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    upload_id: Mapped[int] = mapped_column(ForeignKey(f"{SCHEMA}.sales_day_upload.upload_id"), nullable=False)
    report_date: Mapped[date] = mapped_column(Date, nullable=False)
    recipient_key: Mapped[str] = mapped_column(String(200), nullable=False)
    recipient_name: Mapped[str] = mapped_column(String(200), nullable=False)
    role: Mapped[str] = mapped_column(String(60), nullable=False)
    to_addrs: Mapped[str | None] = mapped_column(String(1000))
    cc_addrs: Mapped[str | None] = mapped_column(String(1000))
    subject: Mapped[str] = mapped_column(String(300), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)                         # JSON: scope (codes) and view
    counts: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(12), nullable=False)
    note: Mapped[str | None] = mapped_column(String(500))
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    outbox_file: Mapped[str | None] = mapped_column(String(500))
    sent_at: Mapped[datetime | None] = mapped_column(UtcDateTime)
    approved_by: Mapped[str | None] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False, default=now_utc)


class SalesJobRun(Base):
    """History of Field Sales jobs (daily from the inbox, month-end), separate from Module 1's job history."""
    __tablename__ = "sales_job_run"
    __table_args__ = (Index("ix_sales_job_run_started", "started_at"), {"schema": SCHEMA})

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job: Mapped[str] = mapped_column(String(20), nullable=False)              # DAILY | MONTHLY
    target: Mapped[str | None] = mapped_column(String(20))
    trigger: Mapped[str] = mapped_column(String(20), nullable=False)          # SCHEDULED | MANUAL | CLI
    status: Mapped[str] = mapped_column(String(10), nullable=False)           # RUNNING | SUCCESS | PARTIAL | FAILED
    summary: Mapped[str | None] = mapped_column(Text)
    error: Mapped[str | None] = mapped_column(String(1000))
    started_by: Mapped[str] = mapped_column(String(100), nullable=False)
    started_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False, default=now_utc)
    finished_at: Mapped[datetime | None] = mapped_column(UtcDateTime)


class SalesLocation(Base):
    """Where someone marked attendance (ATT) or ended the day (EOD) on a day. Kept 6 months."""
    __tablename__ = "sales_location"
    __table_args__ = (UniqueConstraint("code", "day", "kind", name="uq_sales_location"), Index("ix_sales_location_day", "day"),
                      {"schema": SCHEMA})

    id: Mapped[int] = mapped_column(BigId, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(30), nullable=False)
    day: Mapped[date] = mapped_column(Date, nullable=False)
    kind: Mapped[str] = mapped_column(String(4), nullable=False)               # ATT | EOD
    lat: Mapped[float] = mapped_column(Float, nullable=False)
    lng: Mapped[float] = mapped_column(Float, nullable=False)
    time: Mapped[str | None] = mapped_column(String(8))
    source: Mapped[str] = mapped_column(String(10), nullable=False)            # DAY | HISTORY


class SalesDevice(Base):
    """The phone used to mark attendance, as a scrambled code (never the IMEI itself). Kept 6 months."""
    __tablename__ = "sales_device"
    __table_args__ = (UniqueConstraint("code", "day", name="uq_sales_device"), Index("ix_sales_device_day", "day", "device"),
                      {"schema": SCHEMA})

    id: Mapped[int] = mapped_column(BigId, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(30), nullable=False)
    day: Mapped[date] = mapped_column(Date, nullable=False)
    device: Mapped[str] = mapped_column(String(64), nullable=False)


class SalesCall(Base):
    """One outlet visit with its location (Call Variance report). Kept 6 months."""
    __tablename__ = "sales_call"
    __table_args__ = (Index("ix_sales_call_upload", "upload_id"), Index("ix_sales_call_day_code", "day", "code"), {"schema": SCHEMA})

    id: Mapped[int] = mapped_column(BigId, primary_key=True, autoincrement=True)
    upload_id: Mapped[int] = mapped_column(ForeignKey(f"{SCHEMA}.sales_day_upload.upload_id"), nullable=False)
    code: Mapped[str] = mapped_column(String(30), nullable=False)
    day: Mapped[date] = mapped_column(Date, nullable=False)
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    call_id: Mapped[str | None] = mapped_column(String(40))
    start: Mapped[str | None] = mapped_column(String(8))
    end: Mapped[str | None] = mapped_column(String(8))
    duration_s: Mapped[int | None] = mapped_column(Integer)
    lat: Mapped[float | None] = mapped_column(Float)
    lng: Mapped[float | None] = mapped_column(Float)
    outlet_id: Mapped[str | None] = mapped_column(String(40))
    beat_id: Mapped[str | None] = mapped_column(String(40))
    distance_m: Mapped[float | None] = mapped_column(Float)                    # from the outlet, worked out by the app
    productive: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class SalesOutlet(Base):
    """Outlets seen in Call Variance reports: name, beat and fixed location (business data, no phone numbers)."""
    __tablename__ = "sales_outlet"
    __table_args__ = {"schema": SCHEMA}

    outlet_id: Mapped[str] = mapped_column(String(40), primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    beat_id: Mapped[str | None] = mapped_column(String(40))
    beat_name: Mapped[str | None] = mapped_column(String(200))
    category: Mapped[str | None] = mapped_column(String(100))
    pincode: Mapped[str | None] = mapped_column(String(10))
    lat: Mapped[float | None] = mapped_column(Float)
    lng: Mapped[float | None] = mapped_column(Float)
    updated_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False, default=now_utc, onupdate=now_utc)


class SalesCase(Base):
    """The review of one person's day that needs checking: open / checked - OK / action taken, with a note."""
    __tablename__ = "sales_case"
    __table_args__ = (UniqueConstraint("code", "day", name="uq_sales_case"), {"schema": SCHEMA})

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(30), nullable=False)
    day: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(String(10), nullable=False, default="OPEN")   # OPEN | OK | ACTION
    note: Mapped[str | None] = mapped_column(String(1000))
    reason: Mapped[str | None] = mapped_column(String(40))          # why: approved tour / GPS error / staff list wrong / real issue / other
    reviewed_by: Mapped[str | None] = mapped_column(String(100))
    reviewed_at: Mapped[datetime | None] = mapped_column(UtcDateTime)


class SalesHistoryDay(Base):
    """Attendance status per person per day from Bizom's multi-day AttendanceReport (days without a full daily upload)."""
    __tablename__ = "sales_history_day"
    __table_args__ = (UniqueConstraint("code", "day", name="uq_sales_history_day"), Index("ix_sales_history_day_day", "day"),
                      {"schema": SCHEMA})

    id: Mapped[int] = mapped_column(BigId, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(30), nullable=False)
    day: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(String(12), nullable=False)        # present late halfday absent leave week_off not_marked
    present_type: Mapped[str | None] = mapped_column(String(40))
    leave: Mapped[str | None] = mapped_column(String(40))



class SalesPhoto(Base):
    """An attendance selfie's fingerprint (the photo itself is never stored) and its warning signs. Kept keep_months."""
    __tablename__ = "sales_photo"
    __table_args__ = (UniqueConstraint("url", name="uq_sales_photo_url"), Index("ix_sales_photo_status", "status"),
                      Index("ix_sales_photo_day_code", "day", "code"), Index("ix_sales_photo_sha", "sha256"), {"schema": SCHEMA})

    id: Mapped[int] = mapped_column(BigId, primary_key=True, autoincrement=True)
    url: Mapped[str] = mapped_column(String(600), nullable=False)
    kind: Mapped[str] = mapped_column(String(10), nullable=False, default="SELFIE")
    code: Mapped[str] = mapped_column(String(30), nullable=False)
    day: Mapped[date] = mapped_column(Date, nullable=False)
    att_time: Mapped[str | None] = mapped_column(String(8))
    status: Mapped[str] = mapped_column(String(10), nullable=False, default="NEW")      # NEW | DONE | FAILED | SKIPPED
    error: Mapped[str | None] = mapped_column(String(200))
    tries: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    sha256: Mapped[str | None] = mapped_column(String(64))
    phash: Mapped[str | None] = mapped_column(String(16))                               # 64-bit perceptual hash (hex)
    width: Mapped[int | None] = mapped_column(Integer)
    height: Mapped[int | None] = mapped_column(Integer)
    size_kb: Mapped[int | None] = mapped_column(Integer)
    faces: Mapped[int | None] = mapped_column(Integer)
    brightness: Mapped[float | None] = mapped_column(Float)
    sharpness: Mapped[float | None] = mapped_column(Float)
    exif_time: Mapped[str | None] = mapped_column(String(19))                          # "YYYY-MM-DD HH:MM:SS" written by the camera
    flags: Mapped[str | None] = mapped_column(String(300))
    evidence: Mapped[str | None] = mapped_column(Text)
    fetched_at: Mapped[datetime | None] = mapped_column(UtcDateTime)


class SalesDayScore(Base):
    """The learned scores of one person-day: how unusual it is for that person (0-1), whether it counts as an unusual day,
    the risk score 0-100 (all warning signs + unusual-day score) and the plain-language reasons."""
    __tablename__ = "sales_day_score"
    __table_args__ = (UniqueConstraint("code", "day", name="uq_sales_day_score"), Index("ix_sales_day_score_day", "day"), {"schema": SCHEMA})

    id: Mapped[int] = mapped_column(BigId, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(30), nullable=False)
    day: Mapped[date] = mapped_column(Date, nullable=False)
    anomaly: Mapped[float | None] = mapped_column(Float)
    unusual: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    risk: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    reasons: Mapped[str | None] = mapped_column(Text)


class SalesPhotoPair(Base):
    """A pair of selfies whose fingerprints look alike, confirmed (or not) by comparing image details (ORB keypoints +
    RANSAC: how many details line up). Only confirmed pairs become 'reused' / 'same as another person'."""
    __tablename__ = "sales_photo_pair"
    __table_args__ = (UniqueConstraint("a_id", "b_id", name="uq_sales_photo_pair"), {"schema": SCHEMA})

    id: Mapped[int] = mapped_column(BigId, primary_key=True, autoincrement=True)
    a_id: Mapped[int] = mapped_column(BigId, nullable=False)          # the lower photo id
    b_id: Mapped[int] = mapped_column(BigId, nullable=False)
    points: Mapped[int | None] = mapped_column(Integer)                # matching image details; None = could not compare
    checked_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False, default=now_utc)
