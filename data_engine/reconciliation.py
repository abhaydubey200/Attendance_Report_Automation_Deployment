"""Source reconciliation (PRD 9). Compares Bizom and Pocket HRMS per employee/date
and raises exceptions for anything that needs a human decision."""

from __future__ import annotations

import json
from dataclasses import dataclass

from contracts.attendance import ReconciliationCategory as R
from core.config import AttendanceRules
from data_engine.attendance_processor import DayInputs, EngineInputs, is_eligible

SEVERITY = {
    R.EMPLOYEE_MAPPING_MISSING: "HIGH",
    R.STATUS_CONFLICT: "MEDIUM",
    R.LEAVE_CONFLICT: "MEDIUM",
    R.TIME_CONFLICT: "LOW",
    R.DUPLICATE_RECORD: "MEDIUM",
    R.BIZOM_ONLY: "LOW",
    R.HRMS_ONLY: "LOW",
}
NEEDS_EXCEPTION = set(SEVERITY)


@dataclass
class ReconRow:
    category: str
    employee_key: int | None
    source_employee_id: str | None
    department_code: str | None
    bizom_value: str | None
    hrms_value: str | None
    detail: str

    def source_values(self) -> str:
        return json.dumps({"bizom": self.bizom_value, "hrms": self.hrms_value, "detail": self.detail})


def _label(view) -> str | None:
    if not view.present:
        return None
    return view.status or f"UNMAPPED:{view.raw}"


def reconcile(e: EngineInputs, rules: AttendanceRules) -> list[ReconRow]:
    rows: list[ReconRow] = []
    both_sources = {"BIZOM_ATTENDANCE", "HRMS_ATTENDANCE"} <= e.datasets_present
    tolerance = rules.calculation.time_conflict_tolerance_minutes

    for emp in e.employees:
        if not is_eligible(emp, e.day):
            continue
        d = e.inputs.get(emp.employee_key, DayInputs())
        dept = e.org.get(emp.employee_key, (None, None))[0]
        b, h = _label(d.bizom), _label(d.hrms)

        def add(cat: R, detail: str) -> None:
            rows.append(ReconRow(cat.value, emp.employee_key, emp.employee_code, dept, b, h, detail))

        if b is not None and h is not None:
            if b == h:
                add(R.MATCHED, "Sources agree")
            else:
                add(R.STATUS_CONFLICT, f"Bizom reports {b}, Pocket HRMS reports {h}")
            if tolerance is not None and d.bizom.first_in and d.hrms.first_in:
                gap = abs((d.bizom.first_in - d.hrms.first_in).total_seconds()) / 60
                if gap > tolerance:
                    add(R.TIME_CONFLICT, f"First-in times differ by {gap:.0f} minutes")
        elif both_sources and b is not None:
            add(R.BIZOM_ONLY, "Only Bizom has a record")
        elif both_sources and h is not None:
            add(R.HRMS_ONLY, "Only Pocket HRMS has a record")

        if d.leave_approval == "APPROVED":
            clashing = [s for s in (d.bizom.status, d.hrms.status) if s and s not in ("APPROVED_LEAVE", "HALF_DAY")]
            if clashing:
                add(R.LEAVE_CONFLICT, f"Approved leave, but a source reports {', '.join(sorted(set(clashing)))}")

    for dup in e.duplicates:
        rows.append(ReconRow(R.DUPLICATE_RECORD.value, dup["employee_key"], dup["source_employee_id"],
                             e.org.get(dup["employee_key"], (None, None))[0], None, None,
                             f"More than one {dup['source_system']} record for this employee and date"))
    for u in e.unmapped:
        value = u["status"]
        rows.append(ReconRow(R.EMPLOYEE_MAPPING_MISSING.value, None, u["source_employee_id"], None,
                             value if u["source_system"] == "BIZOM" else None,
                             value if u["source_system"] == "POCKET_HRMS" else None,
                             f"{u['source_system']} id {u['source_employee_id']} ({u.get('source_employee_name') or 'no name'}) "
                             "has no verified employee mapping"))
    return rows
