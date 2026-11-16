"""Report-specific readers for exports that are not one-row-per-record tables.

Pocket HRMS "AttendanceSummary" (first real sample, 14-Nov-2026):
  * a preamble (generator line, address, title, "Run Date") above the header row
  * header: Code, Name, Category, Date, Shift Name, In-Out Time, Type, Day, Remarks
  * every employee appears on two consecutive rows: the first carries the in time,
    the second the out time; there is no attendance status column

The reshaper pairs those rows into ONE record per employee and date, and adds a
"Derived Status" made only of observable facts:
  LEAVE:<Type>        a leave/duty code is present (e.g. LEAVE:PL)
  PUNCH_IN_OUT        two or more punch times
  PUNCH_SINGLE        exactly one punch time
  NO_PUNCH            no punch, a shift is assigned
  NO_PUNCH_NO_SHIFT   no punch and "Shift Not Assigned"
What each label MEANS (present, absent, leave...) is an HR decision captured in the
dataset's value map; unmapped labels stay UNRESOLVED.

FINAL layout (approved 16-Nov-2026), detected automatically:
  * header: Code, Name, Category, Department, Designation, Date, Shift Name, In Time, Out Time,
    Duration, Type, Day, Remarks - ONE row per employee (blank spacer rows in between)
  * In/Out Time: HH:MM, "Unswipe" (no punch) or "Invalid" (that punch is missing)
  * Type: Pocket HRMS's own verdict (A / P) or a leave code (PL, SL, CL, ...). A and P are NOT leave codes;
    the app decides present/absent from the punches and the shift, as for the old layout.
  * Remarks: only used to recognise work from home ("wfh", "work from home"); the text is not kept.

Remarks (free text) is deliberately dropped: it is not needed for attendance and
can hold personal or business detail (data minimisation, PRD 21.4).
"""

from __future__ import annotations

import re
from collections import OrderedDict

from ingestion.file_reader import ReadError, Table

SUMMARY_HEADER = ["Code", "Name", "Category", "Date", "Shift Name", "In-Out Time", "Type", "Day", "Remarks"]
SUMMARY_HEADER_V2 = ["Code", "Name", "Category", "Date", "Shift Name", "In Time", "Out Time", "Type"]
HRMS_VERDICTS = {"A", "P", "AB", "PR", "ABSENT", "PRESENT", "MIS", "MISSING"}   # Type values that are not leave codes
_WFH_REMARK = re.compile(r"\b(wfh|work\s*from\s*home)\b", re.IGNORECASE)
SUMMARY_OUTPUT = ["Code", "Name", "Category", "Date", "Shift Name", "In Time", "Out Time", "Punches", "Type", "Day",
                  "Derived Status"]
_TIME = re.compile(r"^\d{1,2}:\d{2}(:\d{2})?$")
NO_SHIFT = "shift not assigned"


def find_header(rows: list[list[str]], required: list[str], scan: int = 25) -> int:
    """Index of the first row containing every required header (case/space-insensitive)."""
    want = {h.strip().lower() for h in required}
    for i, row in enumerate(rows[:scan]):
        have = {str(c).strip().lower() for c in row if str(c).strip()}
        if want <= have:
            return i
    raise ReadError(f"Header row not found; expected columns: {', '.join(required)}.")


def _label(times: list[str], leave_type: str, shift: str) -> str:
    if leave_type:
        return f"LEAVE:{leave_type.strip().upper()}"
    if len(times) >= 2:
        return "PUNCH_IN_OUT"
    if len(times) == 1:
        return "PUNCH_SINGLE"
    return "NO_PUNCH_NO_SHIFT" if shift.strip().lower() == NO_SHIFT else "NO_PUNCH"


def _is_v2(raw_rows: list[list[str]]) -> bool:
    try:
        find_header(raw_rows, SUMMARY_HEADER_V2)
    except ReadError:
        return False
    return True


def reshape_attendance_summary_v2(raw_rows: list[list[str]], first_row_number: int = 1, sheets: list[str] | None = None) -> Table:
    """Final Pocket HRMS layout: one row per employee with separate In Time / Out Time columns."""
    h = find_header(raw_rows, SUMMARY_HEADER_V2)
    header = [str(c).strip() for c in raw_rows[h]]
    idx = {name: i for i, name in enumerate(header) if name}
    rows, numbers, seen = [], [], set()
    for offset, row in enumerate(raw_rows[h + 1:]):
        cells = [str(c).strip() for c in row] + [""] * len(header)
        get = lambda name: cells[idx[name]] if name in idx else ""  # noqa: E731
        code, day = get("Code"), get("Date")
        if not code and not day:
            continue                                        # spacer line
        if (code, day) in seen:
            continue
        seen.add((code, day))
        times = [t for t in (get("In Time"), get("Out Time")) if _TIME.match(t)]
        in_t = get("In Time") if _TIME.match(get("In Time")) else ""
        out_t = get("Out Time") if _TIME.match(get("Out Time")) else ""
        typ = get("Type").upper()
        leave = "" if typ in HRMS_VERDICTS else typ
        rows.append({
            "Code": code, "Name": " ".join(get("Name").split()), "Category": get("Category"), "Date": day,
            "Shift Name": get("Shift Name"),
            # a missing punch keeps the punch that exists in its own column (a lone out-punch is not an arrival)
            "In Time": in_t, "Out Time": out_t,
            "Punches": str(len(times)), "Type": leave, "Day": get("Day"),
            "Derived Status": _label(times, leave, get("Shift Name")),
            "Department": " ".join(get("Department").split()), "Designation": " ".join(get("Designation").split()),
            "HRMS Type": typ, "WFH Remark": "1" if _WFH_REMARK.search(get("Remarks")) else "",
        })
        numbers.append(first_row_number + h + 1 + offset)
    return Table(columns=list(SUMMARY_OUTPUT) + ["Department", "Designation", "HRMS Type", "WFH Remark"], rows=rows,
                 row_numbers=numbers, sheets=sheets or [])


def reshape_attendance_summary(raw_rows: list[list[str]], first_row_number: int = 1, sheets: list[str] | None = None) -> Table:
    if _is_v2(raw_rows):
        return reshape_attendance_summary_v2(raw_rows, first_row_number, sheets)
    h = find_header(raw_rows, SUMMARY_HEADER)
    header = [str(c).strip() for c in raw_rows[h]]
    idx = {name: header.index(name) for name in SUMMARY_HEADER}

    groups: "OrderedDict[tuple[str, str], dict]" = OrderedDict()
    for offset, row in enumerate(raw_rows[h + 1:]):
        cells = [str(c).strip() for c in row] + [""] * len(header)
        get = lambda name: cells[idx[name]]  # noqa: E731
        code, day = get("Code"), get("Date")
        if not code and not day:
            continue                                        # blank line
        key = (code, day)
        g = groups.get(key)
        if g is None:
            g = groups[key] = {"Code": code, "Name": " ".join(get("Name").split()), "Category": get("Category"),
                               "Date": day, "Shift Name": get("Shift Name"), "times": [], "Type": "", "Day": "",
                               "row": first_row_number + h + 1 + offset}
        t = get("In-Out Time")
        if t:
            if not _TIME.match(t):
                g.setdefault("bad_times", []).append(t)
            else:
                g["times"].append(t)
        for col in ("Type", "Day", "Shift Name", "Category", "Name"):
            if not g.get(col) and get(col):
                g[col] = get(col)

    rows, numbers = [], []
    for g in groups.values():
        times = sorted(g["times"], key=lambda s: tuple(int(x) for x in s.split(":")))
        rows.append({
            "Code": g["Code"], "Name": g["Name"], "Category": g["Category"], "Date": g["Date"], "Shift Name": g["Shift Name"],
            "In Time": times[0] if times else "", "Out Time": times[-1] if len(times) >= 2 else "",
            "Punches": str(len(times)), "Type": g["Type"], "Day": g["Day"],
            "Derived Status": _label(times, g["Type"], g["Shift Name"]) if not g.get("bad_times") else "",
        })
        numbers.append(g["row"])
    return Table(columns=list(SUMMARY_OUTPUT), rows=rows, row_numbers=numbers, sheets=sheets or [])


RESHAPERS = {"HRMS_ATTENDANCE_SUMMARY": reshape_attendance_summary}
