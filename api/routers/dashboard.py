"""Executive dashboard (PRD 4.4). Phase 1: explicit empty state. KPI values must only
ever come from validated, approved processing results."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from api.deps import get_settings, require
from api.schemas import DashboardSummary, Kpi
from core.config import Settings, load_attendance_rules
from core.timeutils import today_ist
from security.permissions import Perm, Principal

router = APIRouter(prefix="/dashboard", tags=["dashboard"])

KPIS = (
    ("active_employees", "Active Employees"),
    ("eligible_employees", "Eligible Employees"),
    ("present", "Present"),
    ("absent", "Absent"),
    ("approved_leave", "Approved Leave"),
    ("wfh", "WFH"),
    ("half_day", "Half Day"),
    ("missing_punch", "Missing Punch"),
    ("pending_review", "Pending Review"),
)


@router.get("/summary", response_model=DashboardSummary)
def summary(
    _: Principal = Depends(require(Perm.DASHBOARD_VIEW)),
    settings: Settings = Depends(get_settings),
) -> DashboardSummary:
    rules = load_attendance_rules(settings.config_dir)
    return DashboardSummary(
        today_ist=today_ist(),
        reporting_date=None,
        last_successful_run=None,
        latest_run_status=None,
        uploaded_dataset_count=0,
        rule_version=rules.rule_version,
        rule_approval_status=rules.approval_status,
        rules_approved=rules.is_approved,
        kpis=[Kpi(key=k, label=label) for k, label in KPIS],
        message=(
            "No processed attendance data yet. KPIs appear once datasets have been uploaded, "
            "validated and processed under HR-approved rules (Phases 2-5)."
        ),
    )
