"""Tables of Module 2 - Field Sales attendance (Bizom). Separate from Module 1 (Head Office, Pocket HRMS) tables.

Personal / location data from Bizom (phone numbers, attendance photos, GPS coordinates, outlet mobiles, IMEI) is NEVER
stored: only codes, names, times, statuses, counts and the warning signs worked out from them.
"""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Boolean, Date, Float, ForeignKey, Index, Integer, String, Text
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
