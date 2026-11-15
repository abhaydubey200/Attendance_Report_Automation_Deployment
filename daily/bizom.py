"""Bizom attendance report (field sales app), one day per file.

Layout (CSV or Excel): Zone, SubzoneName, Name, User_Name, User_Id, Employee_Id, Role_id, DOJ, HQ, Designation,
User_Status, Inactive_Date, Imei, Date_DD-MM-YYYY_Attendance_Status, P, SL, PL, Leave, WO, ...

* EMP_CODE = Employee_Id (User_Name can carry suffixes like ``SL01965@MT``).
* Rows without an Employee_Id are vacant positions / test users and are skipped.
* The IMEI column is never read or stored.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime

from ingestion.file_reader import ReadError, read_raw

_DATE_COL = re.compile(r"^date_(\d{1,2})-(\d{1,2})-(\d{4})_attendance_status$", re.IGNORECASE)


class BizomError(ValueError):
    """Shown to the user as-is."""


@dataclass(frozen=True)
class BizomRecord:
    code: str
    name: str
    status: str                 # raw Bizom code: P, A, WO, PL, SL, CL, ...
    designation: str | None
    zone: str | None
    subzone: str | None
    hq: str | None
    active: bool
    inactive_date: date | None


@dataclass
class BizomDay:
    report_date: date
    records: dict[str, BizomRecord]
    skipped_no_id: int


def _clean(v) -> str:
    return re.sub(r"\s+", " ", str(v or "").replace("\xa0", " ")).strip()


def _header_row(rows: list[list[str]]) -> tuple[int, dict[str, int], int, date] | None:
    for i, row in enumerate(rows[:15]):
        cells = [_clean(c) for c in row]
        lower = [c.lower() for c in cells]
        if "employee_id" not in lower or "user_name" not in lower:
            continue
        for j, c in enumerate(cells):
            m = _DATE_COL.match(c)
            if m:
                d, mo, y = (int(x) for x in m.groups())
                return i, {name: lower.index(name) for name in set(lower) if name}, j, date(y, mo, d)
        raise BizomError("Bizom file: no 'Date_DD-MM-YYYY_Attendance_Status' column found. Export one day at a time.")
    return None


def looks_like_bizom(rows: list[list[str]]) -> bool:
    for row in rows[:15]:
        lower = {_clean(c).lower() for c in row}
        if {"employee_id", "user_name"} <= lower:
            return True
    return False


def _parse_date(v: str) -> date | None:
    v = _clean(v)
    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(v, fmt).date()
        except ValueError:
            continue
    return None


def parse_rows(rows: list[list[str]]) -> BizomDay:
    found = _header_row(rows)
    if found is None:
        raise BizomError("Not a Bizom attendance report (needs Employee_Id, User_Name and a Date_..._Attendance_Status column).")
    at, cols, status_col, report_date = found
    status_cols = [j for j, c in enumerate(rows[at]) if _DATE_COL.match(_clean(c))]
    if len(status_cols) > 1:
        raise BizomError(f"The Bizom file covers {len(status_cols)} days; export one day at a time.")

    def get(row, name):
        j = cols.get(name)
        return _clean(row[j]) if j is not None and j < len(row) else ""

    records: dict[str, BizomRecord] = {}
    skipped = 0
    for row in rows[at + 1:]:
        if not any(_clean(c) for c in row):
            continue
        code = get(row, "employee_id").upper()
        if not code:
            skipped += 1
            continue
        status = _clean(row[status_col] if status_col < len(row) else "").upper()
        records[code] = BizomRecord(
            code=code, name=get(row, "name"), status=status, designation=get(row, "designation") or None,
            zone=get(row, "zone") or None, subzone=get(row, "subzonename") or None, hq=get(row, "hq") or None,
            active=get(row, "user_status").lower() != "inactive", inactive_date=_parse_date(get(row, "inactive_date")))
    if not records:
        raise BizomError("The Bizom file has no users with an Employee_Id.")
    return BizomDay(report_date, records, skipped)


def read_bizom(file_type: str, data: bytes) -> BizomDay:
    try:
        rows, _ = read_raw(data, file_type)
    except ReadError as exc:
        raise BizomError(str(exc)) from exc
    return parse_rows(rows)
