"""Server-side page registry (PRD 4.3). The UI renders only what the API says the
principal may see; each data endpoint enforces its own permission regardless."""

from __future__ import annotations

from dataclasses import dataclass

from security.authorization import has_permission
from security.permissions import Perm, Principal


@dataclass(frozen=True)
class PageSpec:
    section: str
    title: str
    slug: str
    permission: Perm
    implemented: bool = False
    phase: int | None = None


P = PageSpec
PAGES: tuple[PageSpec, ...] = (
    P("Overview", "Executive Dashboard", "dashboard", Perm.DASHBOARD_VIEW, implemented=True),
    P("Data Management", "Upload Datasets", "upload", Perm.DATA_UPLOAD, phase=2),
    P("Data Management", "Dataset Registry", "dataset-registry", Perm.DATA_REGISTRY_VIEW, phase=2),
    P("Data Management", "Upload History", "upload-history", Perm.DATA_REGISTRY_VIEW, phase=2),
    P("Data Management", "Data Quality", "data-quality", Perm.DATA_QUALITY_VIEW, phase=3),
    P("Attendance Analytics", "Daily Attendance", "daily-attendance", Perm.ATTENDANCE_VIEW_AGGREGATE, phase=9),
    P("Attendance Analytics", "Employee Attendance", "employee-attendance", Perm.ATTENDANCE_VIEW_EMPLOYEE, phase=9),
    P("Attendance Analytics", "Department Analytics", "department-analytics", Perm.ATTENDANCE_VIEW_AGGREGATE, phase=9),
    P("Attendance Analytics", "Absenteeism", "absenteeism", Perm.ATTENDANCE_VIEW_AGGREGATE, phase=9),
    P("Attendance Analytics", "Leave Analytics", "leave-analytics", Perm.ATTENDANCE_VIEW_AGGREGATE, phase=9),
    P("Attendance Analytics", "Missing Punches", "missing-punches", Perm.ATTENDANCE_VIEW_EMPLOYEE, phase=9),
    P("Reconciliation", "Source Comparison", "source-comparison", Perm.RECONCILIATION_VIEW, phase=6),
    P("Reconciliation", "Conflicting Records", "conflicts", Perm.RECONCILIATION_VIEW, phase=6),
    P("Reconciliation", "Unmapped Employees", "unmapped-employees", Perm.RECONCILIATION_VIEW, phase=4),
    P("Reconciliation", "Exception Resolution", "exception-resolution", Perm.RECONCILIATION_RESOLVE, phase=6),
    P("MIS Reports", "HOD Reports", "hod-reports", Perm.REPORT_VIEW_HOD, phase=8),
    P("MIS Reports", "Directors Reports", "directors-reports", Perm.REPORT_VIEW_DIRECTORS, phase=8),
    P("MIS Reports", "Report Preview", "report-preview", Perm.REPORT_GENERATE, phase=8),
    P("MIS Reports", "Report History", "report-history", Perm.REPORT_GENERATE, phase=8),
    P("AI Intelligence", "Executive Summary", "ai-summary", Perm.AI_USE, phase=11),
    P("AI Intelligence", "Attendance Analyst", "ai-analyst", Perm.AI_USE, phase=12),
    P("Administration", "Users and Roles", "users", Perm.ADMIN_USERS, implemented=True),
    P("Administration", "Department Mapping", "department-mapping", Perm.ADMIN_MAPPING, phase=4),
    P("Administration", "Employee Mapping", "employee-mapping", Perm.ADMIN_MAPPING, phase=4),
    P("Administration", "Attendance Rules", "attendance-rules", Perm.ADMIN_RULES, phase=5),
    P("Administration", "Reporting Hierarchy", "reporting-hierarchy", Perm.ADMIN_RULES, phase=4),
    P("Administration", "Application Settings", "app-settings", Perm.ADMIN_SETTINGS, phase=2),
    P("System Monitoring", "Processing Runs", "processing-runs", Perm.SYSTEM_MONITOR, phase=5),
    P("System Monitoring", "Application Logs", "app-logs", Perm.SYSTEM_MONITOR, phase=2),
    P("System Monitoring", "System Health", "system-health", Perm.SYSTEM_MONITOR, implemented=True),
    P("System Monitoring", "System Configuration", "system-config", Perm.SYSTEM_MONITOR, implemented=True),
)


def visible_pages(principal: Principal | None) -> list[PageSpec]:
    return [p for p in PAGES if has_permission(principal, p.permission)]
