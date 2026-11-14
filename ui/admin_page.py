"""Administration > Users and Roles (read-only in Phase 1; users are created via CLI)."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from core.timeutils import to_ist
from database.connection import session_scope
from database.repositories.security_repository import SecurityRepository
from security.authorization import require_permission
from security.permissions import Perm, Principal
from ui.context import app_engine, app_settings
from ui.theme import page_header


def render_users(principal: Principal) -> None:
    require_permission(principal, Perm.ADMIN_USERS)
    settings = app_settings()
    page_header("Users and Roles", "Create users with: python main.py create-user --username … --role …")

    fmt = settings.app.datetime_format
    with session_scope(app_engine()) as session:
        rows = [
            {
                "Username": u.username,
                "Name": u.display_name,
                "Roles": ", ".join(sorted(r.role.role_code for r in u.roles)),
                "Departments": ", ".join(sorted(d.department_code for d in u.departments)) or "—",
                "Active": u.is_active,
                "Last login (IST)": to_ist(u.last_login_at).strftime(fmt) if u.last_login_at else "—",
            }
            for u in SecurityRepository(session).list_users()
        ]
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")

    st.subheader("Role permissions")
    st.caption(f"Source: config/security.yaml ({settings.security.approval_status}) synced by init-db")
    st.dataframe(
        pd.DataFrame(
            [{"Role": role, "Description": d.description, "Permissions": ", ".join(d.permissions)}
             for role, d in settings.security.roles.items()]
        ),
        hide_index=True, width="stretch",
    )
