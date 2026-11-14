"""attendance.* -- standardized source records, processing runs, daily facts,
reconciliation and exceptions (PRD 8, 9, 10.3, 10.5)."""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Boolean, Date, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from core.timeutils import now_utc
from database.models.base import Base, BigId, UtcDateTime

SCHEMA = "attendance"
_UPLOAD_FK = "staging.upload_registry.upload_id"


class SourceAttendance(Base):
    __tablename__ = "source_attendance"
    __table_args__ = (Index("ix_source_attendance_date_emp", "attendance_date", "source_employee_id"), {"schema": SCHEMA})

    id: Mapped[int] = mapped_column(BigId, primary_key=True, autoincrement=True)
    upload_id: Mapped[int] = mapped_column(ForeignKey(_UPLOAD_FK), nullable=False)
    source_system: Mapped[str] = mapped_column(String(20), nullable=False)
    source_record_id: Mapped[str | None] = mapped_column(String(50))
    source_employee_id: Mapped[str] = mapped_column(String(100), nullable=False)
    source_employee_name: Mapped[str | None] = mapped_column(String(200))
    attendance_date: Mapped[date] = mapped_column(Date, nullable=False)
    source_status: Mapped[str | None] = mapped_column(String(100))
    mapped_status: Mapped[str | None] = mapped_column(String(30))
    first_in: Mapped[datetime | None] = mapped_column(UtcDateTime)
    last_out: Mapped[datetime | None] = mapped_column(UtcDateTime)


class AttendancePunch(Base):
    __tablename__ = "attendance_punch"
    __table_args__ = (Index("ix_attendance_punch_date_emp", "attendance_date", "source_employee_id"), {"schema": SCHEMA})

    id: Mapped[int] = mapped_column(BigId, primary_key=True, autoincrement=True)
    upload_id: Mapped[int] = mapped_column(ForeignKey(_UPLOAD_FK), nullable=False)
    source_system: Mapped[str] = mapped_column(String(20), nullable=False)
    source_record_id: Mapped[str | None] = mapped_column(String(50))
    source_employee_id: Mapped[str] = mapped_column(String(100), nullable=False)
    punch_time: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)
    attendance_date: Mapped[date] = mapped_column(Date, nullable=False)
    direction: Mapped[str] = mapped_column(String(10), nullable=False)
    device_or_location: Mapped[str | None] = mapped_column(String(100))


class LeaveRecordRow(Base):
    __tablename__ = "leave_record"
    __table_args__ = (Index("ix_leave_record_date_emp", "leave_date", "source_employee_id"), {"schema": SCHEMA})

    id: Mapped[int] = mapped_column(BigId, primary_key=True, autoincrement=True)
    upload_id: Mapped[int] = mapped_column(ForeignKey(_UPLOAD_FK), nullable=False)
    source_system: Mapped[str] = mapped_column(String(20), nullable=False)
    source_record_id: Mapped[str | None] = mapped_column(String(50))
    source_employee_id: Mapped[str] = mapped_column(String(100), nullable=False)
    leave_date: Mapped[date] = mapped_column(Date, nullable=False)
    leave_type: Mapped[str | None] = mapped_column(String(100))
    source_approval_status: Mapped[str | None] = mapped_column(String(100))
    approval_status: Mapped[str] = mapped_column(String(20), nullable=False)
    day_portion: Mapped[str] = mapped_column(String(20), nullable=False)


class ProcessingRun(Base):
    """One processing version for a reporting date (PRD 10.5, 19.2)."""

    __tablename__ = "processing_run"
    __table_args__ = (Index("ix_processing_run_date", "reporting_date"), {"schema": SCHEMA})

    run_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_ref: Mapped[str] = mapped_column(String(40), unique=True, nullable=False)
    reporting_date: Mapped[date] = mapped_column(Date, nullable=False)
    version_no: Mapped[int] = mapped_column(Integer, nullable=False)
    input_key: Mapped[str] = mapped_column(String(64), nullable=False)
    inputs: Mapped[str] = mapped_column(Text, nullable=False)          # JSON: upload ids + hashes + config hash
    rule_version: Mapped[str] = mapped_column(String(50), nullable=False)
    rules_approved: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    state: Mapped[str] = mapped_column(String(30), nullable=False)
    is_current: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    ai_status: Mapped[str | None] = mapped_column(String(20))
    stats: Mapped[str | None] = mapped_column(Text)                    # JSON
    error: Mapped[str | None] = mapped_column(String(1000))
    started_by: Mapped[str] = mapped_column(String(100), nullable=False)
    started_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False, default=now_utc)
    finished_at: Mapped[datetime | None] = mapped_column(UtcDateTime)
    approved_by: Mapped[str | None] = mapped_column(String(100))
    approved_at: Mapped[datetime | None] = mapped_column(UtcDateTime)


class FactAttendanceDaily(Base):
    __tablename__ = "fact_attendance_daily"
    __table_args__ = (
        UniqueConstraint("run_id", "employee_key", "attendance_date"),
        Index("ix_fact_attendance_daily_date_dept", "attendance_date", "department_code"),
        {"schema": SCHEMA},
    )

    id: Mapped[int] = mapped_column(BigId, primary_key=True, autoincrement=True)
    run_id: Mapped[int] = mapped_column(ForeignKey(f"{SCHEMA}.processing_run.run_id"), nullable=False)
    employee_key: Mapped[int] = mapped_column(ForeignKey("hr.dim_employee.employee_key"), nullable=False)
    attendance_date: Mapped[date] = mapped_column(Date, nullable=False)
    department_code: Mapped[str | None] = mapped_column(String(50))
    location_code: Mapped[str | None] = mapped_column(String(50))
    final_status: Mapped[str] = mapped_column(String(30), nullable=False)
    bizom_status: Mapped[str | None] = mapped_column(String(30))
    hrms_status: Mapped[str | None] = mapped_column(String(30))
    leave_status: Mapped[str | None] = mapped_column(String(30))
    first_in: Mapped[datetime | None] = mapped_column(UtcDateTime)
    last_out: Mapped[datetime | None] = mapped_column(UtcDateTime)
    punch_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    record_status: Mapped[str] = mapped_column(String(20), nullable=False)  # PROVISIONAL | OFFICIAL
    rule_version: Mapped[str] = mapped_column(String(50), nullable=False)
    reason: Mapped[str | None] = mapped_column(String(300))


class AttendanceReconciliation(Base):
    __tablename__ = "attendance_reconciliation"
    __table_args__ = (Index("ix_attendance_reconciliation_run", "run_id"), {"schema": SCHEMA})

    id: Mapped[int] = mapped_column(BigId, primary_key=True, autoincrement=True)
    run_id: Mapped[int] = mapped_column(ForeignKey(f"{SCHEMA}.processing_run.run_id"), nullable=False)
    employee_key: Mapped[int | None] = mapped_column(Integer)
    source_employee_id: Mapped[str | None] = mapped_column(String(100))
    attendance_date: Mapped[date] = mapped_column(Date, nullable=False)
    category: Mapped[str] = mapped_column(String(30), nullable=False)
    bizom_value: Mapped[str | None] = mapped_column(String(100))
    hrms_value: Mapped[str | None] = mapped_column(String(100))
    detail: Mapped[str | None] = mapped_column(String(300))


class AttendanceException(Base):
    """Exception workflow (PRD 9.4-9.5). Source values are stored and never edited."""

    __tablename__ = "attendance_exceptions"
    __table_args__ = (Index("ix_attendance_exceptions_status", "status"), {"schema": SCHEMA})

    exception_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[int] = mapped_column(ForeignKey(f"{SCHEMA}.processing_run.run_id"), nullable=False)
    employee_key: Mapped[int | None] = mapped_column(Integer)
    source_employee_id: Mapped[str | None] = mapped_column(String(100))
    department_code: Mapped[str | None] = mapped_column(String(50))
    attendance_date: Mapped[date] = mapped_column(Date, nullable=False)
    category: Mapped[str] = mapped_column(String(30), nullable=False)
    severity: Mapped[str] = mapped_column(String(10), nullable=False)  # LOW | MEDIUM | HIGH | CRITICAL
    source_values: Mapped[str] = mapped_column(Text, nullable=False)    # JSON, immutable
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    assigned_to: Mapped[str | None] = mapped_column(String(100))
    resolution: Mapped[str | None] = mapped_column(String(30))
    resolved_status: Mapped[str | None] = mapped_column(String(30))
    resolution_comment: Mapped[str | None] = mapped_column(String(1000))
    resolved_by: Mapped[str | None] = mapped_column(String(100))
    resolved_at: Mapped[datetime | None] = mapped_column(UtcDateTime)
    detected_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False, default=now_utc)


class AttendanceAdjustment(Base):
    """An approved correction. Applied on the next processing run; source data untouched."""

    __tablename__ = "attendance_adjustments"
    __table_args__ = (Index("ix_attendance_adjustments_emp_date", "employee_key", "attendance_date"), {"schema": SCHEMA})

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    exception_id: Mapped[int] = mapped_column(ForeignKey(f"{SCHEMA}.attendance_exceptions.exception_id"), nullable=False)
    employee_key: Mapped[int] = mapped_column(Integer, nullable=False)
    attendance_date: Mapped[date] = mapped_column(Date, nullable=False)
    adjusted_status: Mapped[str] = mapped_column(String(30), nullable=False)
    reason: Mapped[str | None] = mapped_column(String(1000))
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_by: Mapped[str] = mapped_column(String(100), nullable=False)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False, default=now_utc)
