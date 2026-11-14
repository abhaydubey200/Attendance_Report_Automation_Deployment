"""Executive dashboard (PRD 4.4). Phase 1 shows the layout with an explicit empty state:
KPIs must only ever come from validated, approved processing results."""

from __future__ import annotations

import streamlit as st

from core.config import load_attendance_rules
from core.timeutils import now_ist
from security.authorization import require_permission
from security.permissions import Perm, Principal
from ui.context import app_settings
from ui.theme import badge, page_header

KPI_LABELS = (
    "Active Employees", "Eligible Employees", "Present", "Absent", "Approved Leave",
    "WFH", "Half Day", "Missing Punch", "Pending Review",
)


def render(principal: Principal) -> None:
    require_permission(principal, Perm.DASHBOARD_VIEW)
    settings = app_settings()
    rules = load_attendance_rules()

    page_header("Executive Dashboard", f"Today: {now_ist().strftime(settings.app.date_format)} (IST)")

    top = st.columns(4)
    top[0].metric("Reporting date", "—")
    top[1].metric("Last successful run", "—")
    top[2].metric("Latest run status", "—")
    top[3].metric("Uploaded datasets", "0")

    rules_kind = "ok" if rules.is_approved else "warn"
    st.markdown(
        f"Attendance rules {badge(rules.rule_version, 'info')} "
        f"{badge(rules.approval_status.replace('_', ' '), rules_kind)}",
        unsafe_allow_html=True,
    )

    st.info(
        "No processed attendance data yet. KPIs appear here once datasets have been uploaded, "
        "validated and processed under HR-approved rules (Phases 2–5)."
    )

    per_row = 5
    for start in range(0, len(KPI_LABELS), per_row):
        row = st.columns(per_row)
        for col, label in zip(row, KPI_LABELS[start:start + per_row]):
            col.metric(label, "—")
