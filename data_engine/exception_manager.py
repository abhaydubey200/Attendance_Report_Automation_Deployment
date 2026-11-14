"""Exception workflow (PRD 9.4-9.5).

DETECTED -> PENDING_REVIEW -> ASSIGNED -> UNDER_REVIEW -> RESOLVED | REJECTED, every
step written to audit.exception_resolution_log. Original source values are never
edited: a resolution that changes the outcome creates an attendance adjustment that
the next processing run applies. Open exceptions of a run that is replaced by a newer
run become SUPERSEDED.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from contracts.attendance import AttendanceStatus
from core.timeutils import now_utc
from database.models.attendance import AttendanceAdjustment, AttendanceException
from database.models.audit import ExceptionResolutionLog
from security.authorization import can_access_department
from security.permissions import Principal

OPEN = ("PENDING_REVIEW", "ASSIGNED", "UNDER_REVIEW")
TRANSITIONS: dict[str, set[str]] = {
    "DETECTED": {"PENDING_REVIEW"},
    "PENDING_REVIEW": {"ASSIGNED", "SUPERSEDED"},
    "ASSIGNED": {"ASSIGNED", "UNDER_REVIEW", "SUPERSEDED"},
    "UNDER_REVIEW": {"RESOLVED", "REJECTED", "SUPERSEDED"},
    "RESOLVED": set(),
    "REJECTED": set(),
    "SUPERSEDED": set(),
}


class ExceptionWorkflowError(ValueError):
    pass


def _log(session: Session, exc: AttendanceException, to: str, actor: str, comment: str | None = None) -> None:
    if to not in TRANSITIONS[exc.status]:
        raise ExceptionWorkflowError(f"Cannot move an exception from {exc.status} to {to}.")
    session.add(ExceptionResolutionLog(exception_id=exc.exception_id, from_status=exc.status, to_status=to,
                                       actor=actor, comment=(comment or "")[:1000] or None))
    exc.status = to


def create(session: Session, **fields) -> AttendanceException:
    exc = AttendanceException(status="DETECTED", **fields)
    session.add(exc)
    session.flush()
    _log(session, exc, "PENDING_REVIEW", "system:detector")
    return exc


def _get(session: Session, exception_id: int, principal: Principal) -> AttendanceException:
    exc = session.get(AttendanceException, exception_id)
    if exc is None or (exc.department_code and not can_access_department(principal, exc.department_code)):
        raise LookupError("exception not found")
    return exc


def assign(session: Session, exception_id: int, assignee: str, principal: Principal) -> AttendanceException:
    exc = _get(session, exception_id, principal)
    _log(session, exc, "ASSIGNED", principal.username, f"assigned to {assignee}")
    exc.assigned_to = assignee[:100]
    return exc


def start_review(session: Session, exception_id: int, principal: Principal) -> AttendanceException:
    exc = _get(session, exception_id, principal)
    _log(session, exc, "UNDER_REVIEW", principal.username)
    return exc


def resolve(session: Session, exception_id: int, principal: Principal, *, decision: str,
            comment: str, adjusted_status: str | None = None) -> AttendanceException:
    """decision: ADJUST (needs adjusted_status) | NO_CHANGE | REJECT."""
    exc = _get(session, exception_id, principal)
    if not comment or not comment.strip():
        raise ExceptionWorkflowError("A resolution comment is required.")
    if decision == "REJECT":
        _log(session, exc, "REJECTED", principal.username, comment)
    elif decision in ("ADJUST", "NO_CHANGE"):
        if decision == "ADJUST":
            if adjusted_status not in {s.value for s in AttendanceStatus}:
                raise ExceptionWorkflowError("A valid attendance status is required for an adjustment.")
            if exc.employee_key is None:
                raise ExceptionWorkflowError("Map the employee first; an unmapped record cannot be adjusted.")
            for old in session.scalars(select(AttendanceAdjustment).where(
                    AttendanceAdjustment.employee_key == exc.employee_key,
                    AttendanceAdjustment.attendance_date == exc.attendance_date, AttendanceAdjustment.is_active.is_(True))):
                old.is_active = False
            session.add(AttendanceAdjustment(exception_id=exc.exception_id, employee_key=exc.employee_key,
                                             attendance_date=exc.attendance_date, adjusted_status=adjusted_status,
                                             reason=comment[:1000], created_by=principal.username))
            exc.resolved_status = adjusted_status
        _log(session, exc, "RESOLVED", principal.username, comment)
    else:
        raise ExceptionWorkflowError("Unknown decision.")
    exc.resolution, exc.resolution_comment = decision, comment[:1000]
    exc.resolved_by, exc.resolved_at = principal.username, now_utc()
    session.flush()
    return exc


def supersede_open(session: Session, run_ids: list[int]) -> int:
    count = 0
    if not run_ids:
        return 0
    for exc in session.scalars(select(AttendanceException).where(AttendanceException.run_id.in_(run_ids),
                                                                  AttendanceException.status.in_(OPEN))):
        _log(session, exc, "SUPERSEDED", "system:new-run", "replaced by a newer processing run")
        count += 1
    return count
