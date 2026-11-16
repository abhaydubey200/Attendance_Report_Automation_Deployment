"""Pocket HRMS "Permission Report" (short-leave permissions), the second daily dataset.

Layout: a few title rows, then the header EmployeeCode, EmployeeName, AppliedDate, PerDate, PerHour, PerToHour,
ApprovedDate, Reason, Status (Pending / Approved / Rejected / Cancelled). One row per permission.

* Approved permission: excuses a late arrival / early leaving that falls inside its time window.
* Pending permission: nothing is excused; the person is shown with "permission pending HH:MM-HH:MM".
* Rejected / cancelled: ignored.
The free-text Reason is never stored.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime

APPROVED, PENDING, OTHER = "APPROVED", "PENDING", "OTHER"


class PermissionError_(ValueError):
    """Shown to the user as-is."""


@dataclass(frozen=True)
class Permission:
    code: str
    day: date
    start: str          # HH:MM
    end: str            # HH:MM
    status: str         # APPROVED | PENDING | OTHER

    @property
    def window(self) -> str:
        from daily.analysis import t12
        return f"{t12(self.start)} - {t12(self.end)}"


@dataclass
class PermissionDay:
    permissions: list[Permission] = field(default_factory=list)

    @property
    def dates(self) -> set[date]:
        return {p.day for p in self.permissions}


def _clean(v) -> str:
    return re.sub(r"\s+", " ", str(v or "").replace("\xa0", " ")).strip()


def _key(v) -> str:
    return re.sub(r"[^a-z]", "", _clean(v).lower())


REQUIRED = {"employeecode", "perdate", "perhour", "pertohour", "status"}


def looks_like_permission(rows: list[list[str]]) -> bool:
    return any(REQUIRED <= {_key(c) for c in row} for row in rows[:15])


def _date(v: str) -> date:
    v = _clean(v)
    for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y %H:%M", "%Y-%m-%d %H:%M:%S", "%d-%b-%Y"):
        try:
            return datetime.strptime(v, fmt).date()
        except ValueError:
            continue
    raise PermissionError_(f"Unrecognised permission date '{v}'.")


def _time(v: str) -> str:
    v = _clean(v)
    for fmt in ("%H:%M", "%H:%M:%S", "%I:%M %p", "%I:%M%p"):
        try:
            return datetime.strptime(v.upper(), fmt).strftime("%H:%M")
        except ValueError:
            continue
    raise PermissionError_(f"Unrecognised permission time '{v}'.")


def _status(v: str) -> str:
    v = _clean(v).upper()
    if v.startswith("APPROV"):
        return APPROVED
    if v.startswith("PEND") or v in ("APPLIED", "SUBMITTED", "OPEN"):
        return PENDING
    return OTHER


def parse_rows(rows: list[list[str]]) -> PermissionDay:
    header_at = next((i for i, row in enumerate(rows[:15]) if REQUIRED <= {_key(c) for c in row}), None)
    if header_at is None:
        raise PermissionError_("Not a Pocket HRMS Permission Report (needs EmployeeCode, PerDate, PerHour, PerToHour, Status).")
    cols = {_key(c): j for j, c in enumerate(rows[header_at]) if _key(c)}

    def get(row, name):
        j = cols.get(name)
        return row[j] if j is not None and j < len(row) else ""

    out = PermissionDay()
    for n, row in enumerate(rows[header_at + 1:], start=header_at + 2):
        code = _clean(get(row, "employeecode")).upper()
        if not code:
            continue
        try:
            out.permissions.append(Permission(code=code, day=_date(get(row, "perdate")), start=_time(get(row, "perhour")),
                                              end=_time(get(row, "pertohour")), status=_status(get(row, "status"))))
        except PermissionError_ as exc:
            raise PermissionError_(f"Row {n} ({code}): {exc}") from None
    return out
