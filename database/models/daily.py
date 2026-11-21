"""Tables for the daily attendance tool (schema `daily`)."""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Boolean, Date, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from core.timeutils import now_utc
from database.models.base import Base, BigId, UtcDateTime

SCHEMA = "daily"


class DayUpload(Base):
    """One uploaded day. Re-uploading a date replaces it (the old one is kept, not current)."""

    __tablename__ = "day_upload"
    __table_args__ = (Index("ix_day_upload_date", "report_date"), {"schema": SCHEMA})

    upload_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    report_date: Mapped[date] = mapped_column(Date, nullable=False)
    original_filename: Mapped[str | None] = mapped_column(String(255))     # Pocket HRMS file (None = Bizom only so far)
    stored_path: Mapped[str | None] = mapped_column(String(500))
    sha256: Mapped[str | None] = mapped_column(String(64))
    bizom_filename: Mapped[str | None] = mapped_column(String(255))        # Bizom attendance report
    bizom_path: Mapped[str | None] = mapped_column(String(500))
    bizom_sha256: Mapped[str | None] = mapped_column(String(64))           # (Bizom is no longer used; kept for old days)
    permission_filename: Mapped[str | None] = mapped_column(String(255))   # Pocket HRMS Permission Report
    permission_path: Mapped[str | None] = mapped_column(String(500))
    permission_sha256: Mapped[str | None] = mapped_column(String(64))
    is_current: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    employees: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    insights: Mapped[str] = mapped_column(Text, nullable=False)          # JSON computed at upload
    rules: Mapped[str] = mapped_column(Text, nullable=False)             # JSON of the rules used
    uploaded_by: Mapped[str] = mapped_column(String(100), nullable=False)
    uploaded_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False, default=now_utc)


class EmployeeDay(Base):
    __tablename__ = "employee_day"
    __table_args__ = (Index("ix_employee_day_upload", "upload_id"), Index("ix_employee_day_code", "employee_code"),
                      {"schema": SCHEMA})

    id: Mapped[int] = mapped_column(BigId, primary_key=True, autoincrement=True)
    upload_id: Mapped[int] = mapped_column(ForeignKey(f"{SCHEMA}.day_upload.upload_id"), nullable=False)
    employee_code: Mapped[str] = mapped_column(String(50), nullable=False)
    employee_name: Mapped[str | None] = mapped_column(String(200))
    category: Mapped[str] = mapped_column(String(100), nullable=False)      # Pocket HRMS Category (unit)
    department: Mapped[str | None] = mapped_column(String(100))             # from the employee master
    hod_name: Mapped[str | None] = mapped_column(String(200))
    team: Mapped[str | None] = mapped_column(String(100))
    reporting_manager: Mapped[str | None] = mapped_column(String(200))
    shift_name: Mapped[str | None] = mapped_column(String(100))
    in_time: Mapped[str | None] = mapped_column(String(8))              # HH:MM
    out_time: Mapped[str | None] = mapped_column(String(8))
    punches: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    work_minutes: Mapped[int | None] = mapped_column(Integer)
    leave_type: Mapped[str | None] = mapped_column(String(20))
    day_portion: Mapped[str | None] = mapped_column(String(30))
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    late_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    early_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    flags: Mapped[str | None] = mapped_column(String(200))               # comma-separated: LATE,EARLY,SHORT,...
    source: Mapped[str | None] = mapped_column(String(12))               # HRMS | BIZOM | HRMS+BIZOM
    bizom_status: Mapped[str | None] = mapped_column(String(10))
    designation: Mapped[str | None] = mapped_column(String(60))
    hq: Mapped[str | None] = mapped_column(String(100))
    permission: Mapped[str | None] = mapped_column(String(80))            # e.g. "Approved 16:00-18:00"


class AppSetting(Base):
    __tablename__ = "app_setting"
    __table_args__ = {"schema": SCHEMA}

    key: Mapped[str] = mapped_column(String(50), primary_key=True)
    value: Mapped[str] = mapped_column(Text, nullable=False)              # JSON
    updated_by: Mapped[str | None] = mapped_column(String(100))
    updated_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False, default=now_utc, onupdate=now_utc)


class EmailLog(Base):
    __tablename__ = "email_log"
    __table_args__ = (Index("ix_email_log_upload", "upload_id"), {"schema": SCHEMA})

    id: Mapped[int] = mapped_column(BigId, primary_key=True, autoincrement=True)
    upload_id: Mapped[int] = mapped_column(ForeignKey(f"{SCHEMA}.day_upload.upload_id"), nullable=False)
    scope: Mapped[str] = mapped_column(String(100), nullable=False)
    recipients: Mapped[str] = mapped_column(String(2000), nullable=False)   # comma-separated
    subject: Mapped[str] = mapped_column(String(300), nullable=False)
    mode: Mapped[str] = mapped_column(String(10), nullable=False)          # TEST | LIVE
    status: Mapped[str] = mapped_column(String(20), nullable=False)        # SENT | SAVED | FAILED
    error: Mapped[str | None] = mapped_column(String(500))
    outbox_file: Mapped[str | None] = mapped_column(String(500))
    sent_by: Mapped[str] = mapped_column(String(100), nullable=False)
    sent_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False, default=now_utc)


class Employee(Base):
    """Employee master maintained by HR (imported from the HR Excel, edited in the app).
    Leavers are marked LEFT, never deleted, so history stays intact."""

    __tablename__ = "employee"
    __table_args__ = (Index("ix_employee_hod", "hod_name"), {"schema": SCHEMA})

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)       # stored upper-case
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    department: Mapped[str | None] = mapped_column(String(100))
    date_of_joining: Mapped[date | None] = mapped_column(Date)
    hod_name: Mapped[str | None] = mapped_column(String(200))
    hod_email: Mapped[str | None] = mapped_column(String(320))
    team_lead_email: Mapped[str | None] = mapped_column(String(320))               # "Sub split ID"
    also_to: Mapped[str | None] = mapped_column(String(500))     # extra recipients (e.g. a 2nd HOD): also get this person
    reporting_manager: Mapped[str | None] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(10), nullable=False, default="ACTIVE")  # ACTIVE | LEFT
    routing_issue: Mapped[str | None] = mapped_column(String(200))   # e.g. HOD_EMAIL_CONFLICT -> held for HR
    exit_date: Mapped[date | None] = mapped_column(Date)
    source: Mapped[str] = mapped_column(String(10), nullable=False, default="MANUAL")  # IMPORT | MANUAL
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False, default=now_utc)
    updated_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False, default=now_utc, onupdate=now_utc)
    updated_by: Mapped[str | None] = mapped_column(String(100))


class EmployeeChange(Base):
    """Every create / update / leave / restore / import change, with old and new values."""

    __tablename__ = "employee_change"
    __table_args__ = (Index("ix_employee_change_code", "employee_code"), {"schema": SCHEMA})

    id: Mapped[int] = mapped_column(BigId, primary_key=True, autoincrement=True)
    employee_code: Mapped[str] = mapped_column(String(50), nullable=False)
    action: Mapped[str] = mapped_column(String(20), nullable=False)
    changes: Mapped[str | None] = mapped_column(Text)             # JSON {field: [old, new]}
    actor: Mapped[str] = mapped_column(String(100), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False, default=now_utc)


class MailRecipient(Base):
    """Per-recipient switch and display name (Recipient_Master sheet). Absent = active, name derived."""

    __tablename__ = "mail_recipient"
    __table_args__ = {"schema": SCHEMA}

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    email: Mapped[str] = mapped_column(String(320), unique=True, nullable=False)    # lower-case
    name: Mapped[str | None] = mapped_column(String(200))
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    effective_from: Mapped[date | None] = mapped_column(Date)
    effective_to: Mapped[date | None] = mapped_column(Date)
    updated_by: Mapped[str | None] = mapped_column(String(100))


class MailItem(Base):
    """One planned email for one recipient and one day. Content is rendered from the stored lists."""

    __tablename__ = "mail_item"
    __table_args__ = (Index("ix_mail_item_day", "report_date", "recipient_key"), {"schema": SCHEMA})

    id: Mapped[int] = mapped_column(BigId, primary_key=True, autoincrement=True)
    upload_id: Mapped[int] = mapped_column(ForeignKey(f"{SCHEMA}.day_upload.upload_id"), nullable=False)
    report_date: Mapped[date] = mapped_column(Date, nullable=False)
    recipient_key: Mapped[str] = mapped_column(String(320), nullable=False)    # email, DIRECTOR or HR
    recipient_name: Mapped[str] = mapped_column(String(200), nullable=False)
    role: Mapped[str] = mapped_column(String(30), nullable=False)
    to_addrs: Mapped[str | None] = mapped_column(String(2000))
    cc_addrs: Mapped[str | None] = mapped_column(String(2000))
    subject: Mapped[str] = mapped_column(String(300), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)                 # JSON: codes per section
    counts: Mapped[str] = mapped_column(Text, nullable=False)                  # JSON
    status: Mapped[str] = mapped_column(String(20), nullable=False)          # PENDING|SENT|SAVED|FAILED|HELD|DISABLED|DUPLICATE|SUPERSEDED
    note: Mapped[str | None] = mapped_column(String(500))
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    outbox_file: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False, default=now_utc)
    approved_by: Mapped[str | None] = mapped_column(String(100))
    sent_at: Mapped[datetime | None] = mapped_column(UtcDateTime)


class JobRun(Base):
    """One run of an unattended job (daily / monthly / backup / cleanup), for the Automation screen."""

    __tablename__ = "job_run"
    __table_args__ = (Index("ix_job_run_started", "started_at"), {"schema": SCHEMA})

    id: Mapped[int] = mapped_column(BigId, primary_key=True, autoincrement=True)
    job: Mapped[str] = mapped_column(String(20), nullable=False)          # DAILY | MONTHLY | BACKUP | CLEANUP
    target: Mapped[str | None] = mapped_column(String(20))                # 2026-11-14 / 2026-11
    trigger: Mapped[str] = mapped_column(String(20), nullable=False)      # SCHEDULED | MANUAL | CLI
    status: Mapped[str] = mapped_column(String(10), nullable=False)       # RUNNING | SUCCESS | PARTIAL | FAILED | SKIPPED
    summary: Mapped[str | None] = mapped_column(Text)                     # JSON
    error: Mapped[str | None] = mapped_column(String(1000))
    started_by: Mapped[str] = mapped_column(String(100), nullable=False)
    started_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False, default=now_utc)
    finished_at: Mapped[datetime | None] = mapped_column(UtcDateTime)


class MonthlySummary(Base):
    """Month-end result: kept permanently, even after that month's daily rows are cleaned up."""

    __tablename__ = "monthly_summary"
    __table_args__ = {"schema": SCHEMA}

    month: Mapped[str] = mapped_column(String(7), primary_key=True)        # YYYY-MM
    days: Mapped[int] = mapped_column(Integer, nullable=False)
    employees: Mapped[int] = mapped_column(Integer, nullable=False)
    attendance_pct: Mapped[str | None] = mapped_column(String(10))
    summary: Mapped[str] = mapped_column(Text, nullable=False)              # JSON: totals, by HOD, trend
    archive_path: Mapped[str | None] = mapped_column(String(500))           # full daily export of the month (.xlsx)
    archive_sha256: Mapped[str | None] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(12), nullable=False)        # GENERATED | ARCHIVED | CLEANED
    generated_by: Mapped[str] = mapped_column(String(100), nullable=False)
    generated_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False, default=now_utc)
    cleaned_at: Mapped[datetime | None] = mapped_column(UtcDateTime)
