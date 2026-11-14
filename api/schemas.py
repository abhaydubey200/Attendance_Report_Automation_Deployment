"""API request/response models. Versioned with the /api/v1 prefix."""

from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=1, max_length=200)


class NavPage(BaseModel):
    section: str
    title: str
    slug: str
    implemented: bool
    phase: int | None


class Me(BaseModel):
    user_id: int
    username: str
    display_name: str
    roles: list[str]
    permissions: list[str]
    departments: list[str]
    navigation: list[NavPage]
    environment: str
    app_name: str
    idle_timeout_minutes: int
    auth_mode: str


class Kpi(BaseModel):
    key: str
    label: str
    value: float | None = None
    status: str = "NO_DATA"


class DashboardSummary(BaseModel):
    today_ist: date
    reporting_date: date | None
    last_successful_run: datetime | None
    latest_run_status: str | None
    uploaded_dataset_count: int
    rule_version: str
    rule_approval_status: str
    rules_approved: bool
    kpis: list[Kpi]
    message: str


class HealthItem(BaseModel):
    name: str
    status: str
    detail: str


class KeyValue(BaseModel):
    key: str
    value: str


class DatasetRow(BaseModel):
    dataset_id: str
    dataset_name: str
    source_system: str
    frequency: str
    active: bool
    schema_status: str
    columns_defined: int


class SourceAuthorityRow(BaseModel):
    domain: str
    proposed_source: str | None
    authoritative_source: str | None


class SystemConfig(BaseModel):
    application: list[KeyValue]
    datasets: list[DatasetRow]
    rule_version: str
    rule_approval_status: str
    rules: list[KeyValue]
    source_authority: list[SourceAuthorityRow]


class UserRow(BaseModel):
    user_id: int
    username: str
    display_name: str
    roles: list[str]
    departments: list[str]
    is_active: bool
    last_login_at: datetime | None


class RoleRow(BaseModel):
    role: str
    description: str
    permissions: list[str]
