"""KPI calculation (PRD 8.8, 20). Counts are always produced; percentages only when
the HR rules they depend on are approved (PRD 20.3: never publish an unapproved KPI)."""

from __future__ import annotations

from collections import Counter
from typing import Iterable

from contracts.attendance import AttendanceStatus as S
from core.config import AttendanceRules

KPI_STATUSES = [s.value for s in S]


def counts(statuses: Iterable[str]) -> dict[str, int]:
    c = Counter(statuses)
    return {s: c.get(s, 0) for s in KPI_STATUSES}


def percentages(c: dict[str, int], rules: AttendanceRules) -> dict[str, float | None]:
    """Attendance % = present equivalent / eligible working days; absenteeism % = absent / same denominator.
    Returns None for both unless every rule used here is approved."""
    calc = rules.calculation
    needed = (calc.half_day_equivalent, calc.wfh_counts_as_present, calc.approved_leave_in_denominator,
              calc.include_weekly_off_in_denominator, calc.include_holidays_in_denominator)
    if rules.approval_status != "APPROVED" or any(v is None for v in needed):
        return {"attendance_pct": None, "absenteeism_pct": None}
    denominator = sum(c.values()) - c[S.UNRESOLVED] - c[S.PENDING_APPROVAL]
    if not calc.include_weekly_off_in_denominator:
        denominator -= c[S.WEEKLY_OFF]
    if not calc.include_holidays_in_denominator:
        denominator -= c[S.HOLIDAY]
    if not calc.approved_leave_in_denominator:
        denominator -= c[S.APPROVED_LEAVE]
    if denominator <= 0:
        return {"attendance_pct": None, "absenteeism_pct": None}
    present = c[S.PRESENT] + c[S.HALF_DAY] * calc.half_day_equivalent + (c[S.WORK_FROM_HOME] if calc.wfh_counts_as_present else 0)
    return {"attendance_pct": round(100 * present / denominator, 2),
            "absenteeism_pct": round(100 * c[S.ABSENT] / denominator, 2)}


def summarize(statuses: list[str], rules: AttendanceRules, active_employees: int | None = None) -> dict:
    c = counts(statuses)
    return {
        "active_employees": active_employees,
        "eligible_employees": len(statuses),
        "counts": c,
        "pending_review": c[S.UNRESOLVED] + c[S.PENDING_APPROVAL],
        **percentages(c, rules),
        "percentages_status": "APPROVED" if rules.is_approved else "PENDING_HR_APPROVAL",
    }
