"""hr.* -- standardized employee and organisation data (PRD 7, 10.3)."""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Boolean, Date, Float, ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from core.timeutils import now_utc
from database.models.base import Base, UtcDateTime

SCHEMA = "hr"


class DimEmployee(Base):
    """Current employee snapshot. Department/location history lives in employee_org_history."""

    __tablename__ = "dim_employee"
    __table_args__ = {"schema": SCHEMA}

    employee_key: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    employee_code: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    employee_name: Mapped[str | None] = mapped_column(String(200))
    designation: Mapped[str | None] = mapped_column(String(200))
    employment_type: Mapped[str | None] = mapped_column(String(50))
    employment_status: Mapped[str | None] = mapped_column(String(50))
    joining_date: Mapped[date | None] = mapped_column(Date)
    exit_date: Mapped[date | None] = mapped_column(Date)
    department_code: Mapped[str | None] = mapped_column(String(50))
    location_code: Mapped[str | None] = mapped_column(String(50))
    reporting_manager_code: Mapped[str | None] = mapped_column(String(50))
    source_upload_id: Mapped[int | None] = mapped_column(Integer)
    updated_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False, default=now_utc, onupdate=now_utc)


class DimDepartment(Base):
    __tablename__ = "dim_department"
    __table_args__ = {"schema": SCHEMA}

    department_code: Mapped[str] = mapped_column(String(50), primary_key=True)
    department_name: Mapped[str] = mapped_column(String(200), nullable=False)
    parent_department_code: Mapped[str | None] = mapped_column(String(50))
    hod_employee_code: Mapped[str | None] = mapped_column(String(50))
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    source_upload_id: Mapped[int | None] = mapped_column(Integer)
    updated_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False, default=now_utc, onupdate=now_utc)


class EmployeeSourceMapping(Base):
    """Cross-system identity (PRD 7.2). Fuzzy matches are only ever suggestions."""

    __tablename__ = "employee_source_mapping"
    __table_args__ = (UniqueConstraint("source_system", "source_employee_id"), {"schema": SCHEMA})

    mapping_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source_system: Mapped[str] = mapped_column(String(20), nullable=False)
    source_employee_id: Mapped[str] = mapped_column(String(100), nullable=False)
    source_employee_name: Mapped[str | None] = mapped_column(String(200))
    employee_key: Mapped[int | None] = mapped_column(ForeignKey(f"{SCHEMA}.dim_employee.employee_key"))
    status: Mapped[str] = mapped_column(String(20), nullable=False)   # VERIFIED | PENDING | REJECTED
    method: Mapped[str | None] = mapped_column(String(20))             # EXACT_CODE | MANUAL
    suggested_employee_key: Mapped[int | None] = mapped_column(Integer)
    confidence: Mapped[float | None] = mapped_column(Float)
    reviewed_by: Mapped[str | None] = mapped_column(String(100))
    reviewed_at: Mapped[datetime | None] = mapped_column(UtcDateTime)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False, default=now_utc)


class EmployeeOrgHistory(Base):
    """Effective-dated department/location assignment (PRD 7.4). Never overwritten."""

    __tablename__ = "employee_org_history"
    __table_args__ = (Index("ix_employee_org_history_emp_from", "employee_key", "effective_from"), {"schema": SCHEMA})

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    employee_key: Mapped[int] = mapped_column(ForeignKey(f"{SCHEMA}.dim_employee.employee_key"), nullable=False)
    department_code: Mapped[str | None] = mapped_column(String(50))
    location_code: Mapped[str | None] = mapped_column(String(50))
    effective_from: Mapped[date] = mapped_column(Date, nullable=False)
    effective_to: Mapped[date | None] = mapped_column(Date)
    source_upload_id: Mapped[int | None] = mapped_column(Integer)


class ReportingHierarchy(Base):
    __tablename__ = "reporting_hierarchy"
    __table_args__ = {"schema": SCHEMA}

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    employee_code: Mapped[str] = mapped_column(String(50), nullable=False)
    manager_code: Mapped[str | None] = mapped_column(String(50))
    effective_from: Mapped[date] = mapped_column(Date, nullable=False)
    effective_to: Mapped[date | None] = mapped_column(Date)
    source_upload_id: Mapped[int | None] = mapped_column(Integer)


class HolidayCalendar(Base):
    __tablename__ = "holiday_calendar"
    __table_args__ = (UniqueConstraint("holiday_date", "location_code"), {"schema": SCHEMA})

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    holiday_date: Mapped[date] = mapped_column(Date, nullable=False)
    holiday_name: Mapped[str] = mapped_column(String(200), nullable=False)
    location_code: Mapped[str | None] = mapped_column(String(50))  # null = all locations
    source_upload_id: Mapped[int | None] = mapped_column(Integer)
