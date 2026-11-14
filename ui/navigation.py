"""Permission-aware navigation (PRD 4.3).

Pages are only registered when the principal holds the page's permission, AND each
page body re-checks the permission server-side before rendering anything.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import streamlit as st

from security.authorization import has_permission, require_permission
from security.permissions import Perm, Principal
from ui import admin_page, dashboard, system_page
from ui.theme import page_header

Renderer = Callable[[Principal], None]


@dataclass(frozen=True)
class PageSpec:
    section: str
    title: str
    slug: str
    permission: Perm
    renderer: Renderer | None = None   # None => planned page placeholder
    phase: int | None = None
    icon: str = ":material/article:"


def _placeholder(spec: PageSpec) -> Renderer:
    def render(principal: Principal) -> None:
        require_permission(principal, spec.permission)
        page_header(spec.title, spec.section)
        st.info(f"Planned for Phase {spec.phase}. This page is not available yet.")

    return render


PAGES: tuple[PageSpec, ...] = (
    PageSpec("Overview", "Executive Dashboard", "dashboard", Perm.DASHBOARD_VIEW, dashboard.render, icon=":material/dashboard:"),
    # Data Management
    PageSpec("Data Management", "Upload Datasets", "upload", Perm.DATA_UPLOAD, phase=2, icon=":material/upload_file:"),
    PageSpec("Data Management", "Dataset Registry", "dataset-registry", Perm.DATA_REGISTRY_VIEW, phase=2, icon=":material/folder_data:"),
    PageSpec("Data Management", "Upload History", "upload-history", Perm.DATA_REGISTRY_VIEW, phase=2, icon=":material/history:"),
    PageSpec("Data Management", "Data Quality", "data-quality", Perm.DATA_QUALITY_VIEW, phase=3, icon=":material/rule:"),
    # Attendance Analytics
    PageSpec("Attendance Analytics", "Daily Attendance", "daily-attendance", Perm.ATTENDANCE_VIEW_AGGREGATE, phase=9, icon=":material/today:"),
    PageSpec("Attendance Analytics", "Employee Attendance", "employee-attendance", Perm.ATTENDANCE_VIEW_EMPLOYEE, phase=9, icon=":material/person_search:"),
    PageSpec("Attendance Analytics", "Department Analytics", "department-analytics", Perm.ATTENDANCE_VIEW_AGGREGATE, phase=9, icon=":material/bar_chart:"),
    PageSpec("Attendance Analytics", "Absenteeism", "absenteeism", Perm.ATTENDANCE_VIEW_AGGREGATE, phase=9, icon=":material/trending_down:"),
    PageSpec("Attendance Analytics", "Leave Analytics", "leave-analytics", Perm.ATTENDANCE_VIEW_AGGREGATE, phase=9, icon=":material/event_busy:"),
    PageSpec("Attendance Analytics", "Missing Punches", "missing-punches", Perm.ATTENDANCE_VIEW_EMPLOYEE, phase=9, icon=":material/fingerprint:"),
    # Reconciliation
    PageSpec("Reconciliation", "Source Comparison", "source-comparison", Perm.RECONCILIATION_VIEW, phase=6, icon=":material/compare_arrows:"),
    PageSpec("Reconciliation", "Conflicting Records", "conflicts", Perm.RECONCILIATION_VIEW, phase=6, icon=":material/report:"),
    PageSpec("Reconciliation", "Unmapped Employees", "unmapped-employees", Perm.RECONCILIATION_VIEW, phase=4, icon=":material/link_off:"),
    PageSpec("Reconciliation", "Exception Resolution", "exception-resolution", Perm.RECONCILIATION_RESOLVE, phase=6, icon=":material/task_alt:"),
    # MIS Reports
    PageSpec("MIS Reports", "HOD Reports", "hod-reports", Perm.REPORT_VIEW_HOD, phase=8, icon=":material/description:"),
    PageSpec("MIS Reports", "Directors Reports", "directors-reports", Perm.REPORT_VIEW_DIRECTORS, phase=8, icon=":material/summarize:"),
    PageSpec("MIS Reports", "Report Preview", "report-preview", Perm.REPORT_GENERATE, phase=8, icon=":material/preview:"),
    PageSpec("MIS Reports", "Report History", "report-history", Perm.REPORT_GENERATE, phase=8, icon=":material/inventory_2:"),
    # AI Intelligence
    PageSpec("AI Intelligence", "Executive Summary", "ai-summary", Perm.AI_USE, phase=11, icon=":material/auto_awesome:"),
    PageSpec("AI Intelligence", "Attendance Analyst", "ai-analyst", Perm.AI_USE, phase=12, icon=":material/chat:"),
    # Administration
    PageSpec("Administration", "Users and Roles", "users", Perm.ADMIN_USERS, admin_page.render_users, icon=":material/group:"),
    PageSpec("Administration", "Department Mapping", "department-mapping", Perm.ADMIN_MAPPING, phase=4, icon=":material/account_tree:"),
    PageSpec("Administration", "Employee Mapping", "employee-mapping", Perm.ADMIN_MAPPING, phase=4, icon=":material/badge:"),
    PageSpec("Administration", "Attendance Rules", "attendance-rules", Perm.ADMIN_RULES, phase=5, icon=":material/gavel:"),
    PageSpec("Administration", "Reporting Hierarchy", "reporting-hierarchy", Perm.ADMIN_RULES, phase=4, icon=":material/lan:"),
    PageSpec("Administration", "Application Settings", "app-settings", Perm.ADMIN_SETTINGS, phase=2, icon=":material/settings:"),
    # System Monitoring
    PageSpec("System Monitoring", "Processing Runs", "processing-runs", Perm.SYSTEM_MONITOR, phase=5, icon=":material/sync:"),
    PageSpec("System Monitoring", "Application Logs", "app-logs", Perm.SYSTEM_MONITOR, phase=2, icon=":material/terminal:"),
    PageSpec("System Monitoring", "Database Health", "db-health", Perm.SYSTEM_MONITOR, system_page.render_health, icon=":material/monitor_heart:"),
    PageSpec("System Monitoring", "System Configuration", "system-config", Perm.SYSTEM_MONITOR, system_page.render_configuration, icon=":material/tune:"),
)


def _no_access(principal: Principal) -> None:
    page_header("No pages available")
    st.warning("Your account has no permissions assigned. Contact the system administrator.")


def visible_pages(principal: Principal) -> list[PageSpec]:
    return [p for p in PAGES if has_permission(principal, p.permission)]


def build_navigation(principal: Principal) -> dict[str, list]:
    sections: dict[str, list] = {}
    for spec in visible_pages(principal):
        renderer = spec.renderer or _placeholder(spec)
        page = st.Page(
            (lambda r=renderer: r(principal)),
            title=spec.title,
            url_path=spec.slug,
            icon=spec.icon,
            default=(spec.slug == "dashboard") or (not sections and not has_permission(principal, Perm.DASHBOARD_VIEW)),
        )
        sections.setdefault(spec.section, []).append(page)
    if not sections:
        sections["Account"] = [st.Page(lambda: _no_access(principal), title="No access", url_path="no-access", default=True)]
    return sections
