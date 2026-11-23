"""Pocket HRMS "On Duty Report" (OnDutyReportAdmin), the third daily dataset: work done away from the office punch
machine - on duty outside (client visit, audit, exhibition) or work from home.

Layout (Pocket HRMS saves it as an HTML table named .xls): a few title rows, then the header Company Name, Employee Code,
Employee Name, On Duty Date, In Date, In Time, Out Date, Out Time, Created Date, Total On Duty Hours, Day Type, Type,
Employee Remarks, Overall Status, Manager Name 1, Manager Status 1, ... One row per request.

* Approved, full day: the person is "On duty" (or "Work from home" when the request says so) - counted present, and
  late / left early / short hours do not apply. A leave, week off or holiday recorded that day is kept as it is.
* Approved, part of the day: works like an approved short leave for that time window (excuses late / early inside it).
* Pending: nothing changes; the person is shown with "On duty pending" and HR's action list asks for approval.
* Rejected / cancelled: ignored.

The free-text Employee Remarks are never stored: they are only read to tell work from home from on duty outside.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date

from daily.permissions import APPROVED, OTHER, PENDING, PermissionError_, _clean, _date, _key, _time


def _status(v: str) -> str:
    """Approved / rejected / cancelled are final; anything else (Pending, Partially approved, Applied, ...) is pending:
    shown, but it changes nothing."""
    v = _clean(v).upper()
    if v.startswith("APPROV"):
        return APPROVED
    if v.startswith(("REJECT", "CANCEL", "WITHDRAW", "DECLIN")):
        return OTHER
    return PENDING

__all__ = ["APPROVED", "PENDING", "OTHER", "OnDuty", "OnDutyDay", "looks_like_onduty", "parse_rows"]

ON_DUTY, WFH = "ON_DUTY", "WFH"
_WFH = re.compile(r"\bw\s*\.?\s*f\s*\.?\s*h\b|work(ing)?\s*(from|frm|for)\s*home|\bhome\s*office\b", re.IGNORECASE)


@dataclass(frozen=True)
class OnDuty:
    code: str
    day: date
    start: str | None       # HH:MM (None when the report has no time)
    end: str | None
    full_day: bool
    kind: str               # ON_DUTY | WFH
    status: str             # APPROVED | PENDING | OTHER

    @property
    def label(self) -> str:
        """e.g. "Work from home approved (full day)" / "On duty pending (9:30 AM - 1:30 PM)"."""
        from daily.analysis import t12
        what = "Work from home" if self.kind == WFH else "On duty"
        state = "approved" if self.status == APPROVED else "pending"
        when = "full day" if self.full_day or not (self.start and self.end) else f"{t12(self.start)} - {t12(self.end)}"
        return f"{what} {state} ({when})"


@dataclass
class OnDutyDay:
    requests: list[OnDuty] = field(default_factory=list)

    @property
    def dates(self) -> set[date]:
        return {r.day for r in self.requests}


REQUIRED = {"employeecode", "ondutydate", "overallstatus"}


def looks_like_onduty(rows: list[list[str]]) -> bool:
    return any(REQUIRED <= {_key(c) for c in row} for row in rows[:15])


def _full_day(day_type: str, start: str | None, end: str | None) -> bool:
    t = _clean(day_type).lower()
    if "half" in t or "hour" in t or "partial" in t:
        return False
    if "full" in t:
        return True
    if start and end:                                          # no day type: 7+ hours is a full day
        a, b = (int(x[:2]) * 60 + int(x[3:]) for x in (start, end))
        return (b - a) % (24 * 60) >= 7 * 60
    return True


def parse_rows(rows: list[list[str]]) -> OnDutyDay:
    header_at = next((i for i, row in enumerate(rows[:15]) if REQUIRED <= {_key(c) for c in row}), None)
    if header_at is None:
        raise PermissionError_("Not a Pocket HRMS On Duty Report (needs Employee Code, On Duty Date, Overall Status).")
    cols: dict[str, int] = {}
    for j, c in enumerate(rows[header_at]):
        cols.setdefault(_key(c), j)                            # first "Manager Status 1" etc. wins; not used anyway

    def get(row, name):
        j = cols.get(name)
        return row[j] if j is not None and j < len(row) else ""

    out = OnDutyDay()
    for n, row in enumerate(rows[header_at + 1:], start=header_at + 2):
        code = _clean(get(row, "employeecode")).upper()
        if not code:
            continue
        try:
            start = _time(get(row, "intime")) if _clean(get(row, "intime")) else None
            end = _time(get(row, "outtime")) if _clean(get(row, "outtime")) else None
            text = f"{get(row, 'type')} {get(row, 'employeeremarks')}"
            out.requests.append(OnDuty(code=code, day=_date(get(row, "ondutydate")), start=start, end=end,
                                       full_day=_full_day(get(row, "daytype"), start, end),
                                       kind=WFH if _WFH.search(text) else ON_DUTY, status=_status(get(row, "overallstatus"))))
        except PermissionError_ as exc:
            raise PermissionError_(f"Row {n} ({code}): {str(exc).replace('permission ', '')}") from None
    return out
