"""Cross-system employee identity (PRD 7.2-7.3).

Priority: an approved mapping -> exact employee-code match -> manual review.
Name similarity may SUGGEST a candidate; it never establishes an identity.
"""

from __future__ import annotations

import difflib

from sqlalchemy import select
from sqlalchemy.orm import Session

from core.timeutils import now_utc
from database.models.hr import DimEmployee, EmployeeSourceMapping

SUGGESTION_THRESHOLD = 0.75


def _suggest(name: str | None, employees: list[DimEmployee]) -> tuple[int | None, float | None]:
    if not name:
        return None, None
    best_key, best_score = None, 0.0
    target = name.strip().lower()
    for emp in employees:
        if not emp.employee_name:
            continue
        score = difflib.SequenceMatcher(None, target, emp.employee_name.strip().lower()).ratio()
        if score > best_score:
            best_key, best_score = emp.employee_key, score
    return (best_key, round(best_score, 3)) if best_score >= SUGGESTION_THRESHOLD else (None, None)


def ensure_mappings(session: Session, source_system: str, ids_and_names: dict[str, str | None]) -> dict[str, int]:
    """Create mapping rows for unseen source ids. Returns counts by resulting status."""
    if not ids_and_names:
        return {}
    existing = {m.source_employee_id: m for m in session.scalars(
        select(EmployeeSourceMapping).where(EmployeeSourceMapping.source_system == source_system,
                                            EmployeeSourceMapping.source_employee_id.in_(list(ids_and_names))))}
    by_code = {e.employee_code: e for e in session.scalars(select(DimEmployee))}
    employees = list(by_code.values())
    counts: dict[str, int] = {}
    for source_id, name in ids_and_names.items():
        mapping = existing.get(source_id)
        if mapping is None:
            emp = by_code.get(source_id)
            if emp is not None:
                mapping = EmployeeSourceMapping(source_system=source_system, source_employee_id=source_id,
                                                source_employee_name=name, employee_key=emp.employee_key,
                                                status="VERIFIED", method="EXACT_CODE", reviewed_by="system:exact-code",
                                                reviewed_at=now_utc())
            else:
                key, score = _suggest(name, employees)
                mapping = EmployeeSourceMapping(source_system=source_system, source_employee_id=source_id,
                                                source_employee_name=name, status="PENDING",
                                                suggested_employee_key=key, confidence=score)
            session.add(mapping)
        counts[mapping.status] = counts.get(mapping.status, 0) + 1
    session.flush()
    return counts


def refresh_exact_matches(session: Session) -> int:
    """After a new employee master: verify pending mappings whose id now matches a code exactly."""
    by_code = {e.employee_code: e.employee_key for e in session.scalars(select(DimEmployee))}
    changed = 0
    for m in session.scalars(select(EmployeeSourceMapping).where(EmployeeSourceMapping.status == "PENDING")):
        if m.source_employee_id in by_code:
            m.employee_key, m.status, m.method = by_code[m.source_employee_id], "VERIFIED", "EXACT_CODE"
            m.reviewed_by, m.reviewed_at = "system:exact-code", now_utc()
            changed += 1
    return changed


def resolve_mapping(session: Session, mapping_id: int, employee_key: int | None, actor: str, reject: bool = False) -> EmployeeSourceMapping:
    mapping = session.get(EmployeeSourceMapping, mapping_id)
    if mapping is None:
        raise LookupError("mapping not found")
    if reject:
        mapping.status, mapping.employee_key = "REJECTED", None
    else:
        if employee_key is None or session.get(DimEmployee, employee_key) is None:
            raise ValueError("a valid employee must be selected")
        mapping.status, mapping.employee_key = "VERIFIED", employee_key
    mapping.method, mapping.reviewed_by, mapping.reviewed_at = "MANUAL", actor, now_utc()
    session.flush()
    return mapping


def verified_lookup(session: Session) -> dict[tuple[str, str], int]:
    """(source_system, source_employee_id) -> employee_key for VERIFIED mappings."""
    return {(m.source_system, m.source_employee_id): m.employee_key
            for m in session.scalars(select(EmployeeSourceMapping).where(EmployeeSourceMapping.status == "VERIFIED"))
            if m.employee_key is not None}
