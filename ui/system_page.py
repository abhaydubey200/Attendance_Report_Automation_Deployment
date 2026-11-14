"""System Monitoring pages: Database Health and System Configuration."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from core.config import load_attendance_rules, load_source_authority
from ingestion.dataset_registry import load_dataset_registry
from monitoring.health import Status, run_all
from security.authorization import require_permission
from security.permissions import Perm, Principal
from ui.context import app_engine, app_settings
from ui.theme import badge, page_header

_KIND = {Status.OK: "ok", Status.WARN: "warn", Status.FAIL: "fail"}


def render_health(principal: Principal) -> None:
    require_permission(principal, Perm.SYSTEM_MONITOR)
    page_header("Database & System Health")
    settings = app_settings()
    for check in run_all(settings, app_engine()):
        st.markdown(f"{badge(check.status, _KIND[check.status])} **{check.name}** — {check.detail}", unsafe_allow_html=True)


def render_configuration(principal: Principal) -> None:
    require_permission(principal, Perm.SYSTEM_MONITOR)
    settings = app_settings()
    page_header("System Configuration", "Read-only view. Secrets are never displayed.")

    st.subheader("Application")
    st.dataframe(
        pd.DataFrame(
            [
                ("Environment", settings.environment),
                ("Timezone", settings.app.timezone),
                ("Database profile", f"{settings.database.name} ({settings.database.backend})"),
                ("Max upload size", f"{settings.uploads.max_file_size_mb} MB"),
                ("Allowed extensions", ", ".join(settings.uploads.allowed_extensions)),
                ("Idle timeout", f"{settings.session.idle_timeout_minutes} min"),
                ("Email distribution", "enabled" if settings.features.email_enabled else "disabled"),
                ("AI", "enabled" if settings.features.ai_enabled else "disabled"),
            ],
            columns=["Setting", "Value"],
        ),
        hide_index=True, width="stretch",
    )

    st.subheader("Dataset registry")
    registry = load_dataset_registry(settings.config_dir)
    st.dataframe(
        pd.DataFrame(
            [
                {
                    "Dataset": d.dataset_id, "Name": d.dataset_name, "Source": d.source_system.value,
                    "Frequency": d.frequency, "Active": d.active, "Schema": d.schema_status.value,
                    "Columns defined": len(d.required_columns),
                }
                for d in registry.datasets
            ]
        ),
        hide_index=True, width="stretch",
    )

    st.subheader("Attendance rules")
    rules = load_attendance_rules(settings.config_dir)
    st.write(f"Version **{rules.rule_version}** — {rules.approval_status}")
    st.dataframe(
        pd.DataFrame(
            [{"Rule": k, "Value": "PENDING HR DECISION" if v is None else str(v)}
             for k, v in rules.calculation.model_dump().items()]
        ),
        hide_index=True, width="stretch",
    )

    st.subheader("Source authority")
    authority = load_source_authority(settings.config_dir)
    st.dataframe(
        pd.DataFrame(
            [{"Domain": k, "Proposed": v.proposed_source or "—", "Approved": v.authoritative_source or "PENDING HR"}
             for k, v in authority.domains.items()]
        ),
        hide_index=True, width="stretch",
    )
