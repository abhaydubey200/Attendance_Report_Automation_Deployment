"""Self-check of every Field Sales upload, before any email is prepared.

The Bizom Attendance report is read AGAIN with a separate, deliberately simple reader (plain column names, no shared
parsing code) and every person's stored status and attendance time is compared with it. People not in the file must be
on the staff list, have joined by that day, and be absent (or week off / holiday on an off day). Any difference holds the
day's emails until it is explained - nothing wrong reaches a HOD.
"""

from __future__ import annotations

import csv
import io
import re
from datetime import date

ABSENT_LIKE = {"ABSENT", "WEEK_OFF"}


def _hhmm(v: str) -> str | None:
    m = re.match(r"^\s*(\d{1,2}):(\d{1,2})(?::\d{1,2})?\s*([AaPp][Mm])?\s*$", v or "")
    if not m:
        return None
    h, mi, ap = int(m.group(1)), int(m.group(2)), (m.group(3) or "").upper()
    h = h + 12 if ap == "PM" and h < 12 else 0 if ap == "AM" and h == 12 else h
    return f"{h:02d}:{mi:02d}" if h < 24 and mi < 60 else None


def _expected(status: str, leave: str) -> str:
    s, lv = (status or "").strip().lower(), (leave or "").strip()
    if s == "present":
        return "PRESENT"
    if s == "late":
        return "LATE"
    if s == "halfday":
        return "HALF_DAY"
    if lv.lower().startswith("weekly off") or lv.lower() in ("wo", "week off"):
        return "WEEK_OFF"
    return "LEAVE" if lv else "ABSENT"


def raw_attendance(data: bytes) -> dict[str, dict]:
    """Emp Id -> {status, time} straight from the Bizom CSV (first row per code wins, like the importer)."""
    text = data.decode("utf-8-sig", errors="replace")
    out: dict[str, dict] = {}
    for r in csv.DictReader(io.StringIO(text)):
        r = {(k or "").strip().lower(): (v or "") for k, v in r.items()}
        code = re.sub(r"@.*$", "", (r.get("emp id") or "").strip()).upper()
        if not re.match(r"^[A-Z]{2}\d{3,}$", code) or code in out:
            continue
        out[code] = {"status": _expected(r.get("status", ""), r.get("leave details", "")), "time": _hhmm(r.get("attendance time", ""))}
    return out


def check(day: date, attendance_csv: bytes | None, stored: list, staff: dict, off_day: str | None,
          left_out: set[str] = frozenset(), holiday_codes: set[str] = frozenset()) -> dict:
    """stored: SalesEmployeeDay rows of the upload; staff: code -> SalesEmployee; left_out: codes deliberately not reported
    (promoters, excluded codes). Returns {checked, mismatches: [...]}."""
    if attendance_csv is None or attendance_csv[:2] == b"PK":
        return {"checked": 0, "mismatches": [], "mismatch_count": 0, "note": "Excel copy, not Bizom's CSV export - checked by the importer only."}
    raw = raw_attendance(attendance_csv)
    bad = []
    for r in stored:
        x = raw.get(r.code)
        if x is not None:
            if r.status != x["status"]:
                bad.append(f"{r.code}: stored {r.status}, Bizom says {x['status']}")
            elif (r.attendance_time or None) != x["time"] and r.status not in ("LEAVE", "WEEK_OFF", "ABSENT"):
                bad.append(f"{r.code}: stored time {r.attendance_time}, Bizom says {x['time']}")
            continue
        e = staff.get(r.code)
        if e is None:
            bad.append(f"{r.code}: not in Bizom's file and not on the staff list")
        elif e.date_of_joining and e.date_of_joining > day:
            bad.append(f"{r.code}: counted before joining on {e.date_of_joining:%d-%b-%Y}")
        elif r.status not in ABSENT_LIKE or (r.status == "WEEK_OFF") != bool(off_day or r.code in holiday_codes):
            bad.append(f"{r.code}: not in Bizom's file but stored {r.status}")
    stored_codes = {r.code for r in stored}
    missing = [c for c, x in raw.items() if c not in stored_codes and c in staff and c not in left_out]
    bad += [f"{c}: in Bizom's file ({raw[c]['status']}) but not stored" for c in missing]
    return {"checked": len(stored), "in_file": len(raw), "mismatches": bad[:50], "mismatch_count": len(bad)}
