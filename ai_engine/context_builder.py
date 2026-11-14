"""Builds the ONLY material the model may use: aggregated, validated metrics.
No names, no employee codes, no free text from source files (PRD 14.2, 21.4)."""

from __future__ import annotations

import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from database.models.attendance import ProcessingRun


def _strip(kpis: dict) -> dict:
    return {"eligible": kpis.get("eligible_employees"), "counts": kpis.get("counts", {}),
            "attendance_pct": kpis.get("attendance_pct"), "absenteeism_pct": kpis.get("absenteeism_pct")}


def run_context(session: Session, run: ProcessingRun) -> dict:
    stats = json.loads(run.stats or "{}")
    previous = session.scalar(select(ProcessingRun).where(ProcessingRun.is_current.is_(True),
                                                          ProcessingRun.reporting_date < run.reporting_date)
                              .order_by(ProcessingRun.reporting_date.desc()))
    prev_stats = json.loads(previous.stats or "{}") if previous else {}
    return {
        "reporting_date": run.reporting_date.isoformat(),
        "run": run.run_ref,
        "rules_approved": run.rules_approved,
        "organisation": _strip(stats.get("kpis", {})),
        "departments": {k: _strip(v) for k, v in stats.get("departments", {}).items()},
        "reconciliation": stats.get("reconciliation", {}).get("counts", {}),
        "missing_datasets": stats.get("missing_datasets", []),
        "previous_day": {"reporting_date": previous.reporting_date.isoformat(),
                         "organisation": _strip(prev_stats.get("kpis", {}))} if previous else None,
    }


def numbers_in(obj) -> set[str]:
    """Every number that appears anywhere in the context, as text (for output checking)."""
    out: set[str] = set()
    if isinstance(obj, dict):
        for v in obj.values():
            out |= numbers_in(v)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            out |= numbers_in(v)
    elif isinstance(obj, bool) or obj is None:
        pass
    elif isinstance(obj, (int, float)):
        out.add(f"{obj:g}")
        if isinstance(obj, float):
            out.add(f"{obj:.2f}".rstrip("0").rstrip("."))
    elif isinstance(obj, str):
        import re
        out |= set(re.findall(r"\d+(?:\.\d+)?", obj))
    return out
