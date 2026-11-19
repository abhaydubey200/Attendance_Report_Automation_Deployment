"""Read the three Bizom exports. Each file is recognised by its columns, one day per file.

* Attendance report      - one row per user who MARKED attendance: status, times, time in market, KM, manager names.
* Attendance & EOD report - every active user, "Marked" / "Not Marked", end-of-day time. Names only (no code).
* Call Variance report   - one row per outlet visit: times, distance from the outlet, productive or not, order value.

Never kept: phone numbers, photo links, GPS coordinates, addresses, outlet mobiles, IMEI. GPS of the call report is used
in memory only, to work out the distance between consecutive calls (impossible travel); just the count is kept.
"""

from __future__ import annotations

import math
import re
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime

ATTENDANCE, EOD, CALLS = "ATTENDANCE", "EOD", "CALLS"
LABEL = {ATTENDANCE: "Bizom Attendance report", EOD: "Bizom Attendance & EOD report", CALLS: "Bizom Call Variance report"}


class BizomError(ValueError):
    """Shown to the user as-is."""


def _clean(v) -> str:
    return re.sub(r"\s+", " ", str(v or "").replace("\xa0", " ")).strip()


def norm_code(v: str) -> str:
    """'SL04188@MT' -> 'SL04188' (Bizom user names can carry a suffix)."""
    return _clean(v).split("@")[0].upper()


def norm_name(v: str) -> str:
    return _clean(v).upper()


def hhmm(v: str) -> str | None:
    """'09:07:49' / '9:7' / '08:00 PM' -> '09:07' / '20:00' (24 h); blank -> None."""
    v = _clean(v)
    if not v:
        return None
    m = re.match(r"^(\d{1,2}):(\d{1,2})(?::\d{1,2})?\s*([AaPp][Mm])?$", v)
    if not m:
        return None
    h, mi, ap = int(m.group(1)), int(m.group(2)), (m.group(3) or "").upper()
    if ap == "PM" and h < 12:
        h += 12
    if ap == "AM" and h == 12:
        h = 0
    return f"{h:02d}:{mi:02d}" if h < 24 and mi < 60 else None


def seconds(v: str) -> int | None:
    """Duration 'H:M:S' (e.g. '0:1:45', '08:15:28') -> seconds."""
    parts = _clean(v).split(":")
    if len(parts) != 3 or not all(p.isdigit() for p in parts):
        return None
    return int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])


def minutes_of(t: str | None) -> int | None:
    return int(t[:2]) * 60 + int(t[3:5]) if t else None


def _num(v: str) -> float | None:
    try:
        return float(_clean(v).replace(",", ""))
    except ValueError:
        return None


def _date(v: str) -> date | None:
    v = _clean(v)
    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%Y/%m/%d", "%d-%b-%Y"):
        try:
            return datetime.strptime(v[:11].strip(), fmt).date()
        except ValueError:
            continue
    return None


# ---------------------------------------------------------------- recognising a file
_SIGNATURE = {
    ATTENDANCE: {"emp id", "status", "attendance time", "time spent in market"},
    EOD: {"user_name", "for_date", "eod_time", "status"},
    CALLS: {"call_id", "call_start_time", "distance_variance(mtrs)"},
}


def _header(rows: list[list[str]]) -> tuple[int, str, dict[str, int]] | None:
    for i, row in enumerate(rows[:10]):
        lower = [_clean(c).lower() for c in row]
        for kind, sig in _SIGNATURE.items():
            if sig <= set(lower):
                return i, kind, {name: j for j, name in enumerate(lower) if name}
    return None


def kind_of(rows: list[list[str]]) -> str | None:
    found = _header(rows)
    return found[1] if found else None


# ---------------------------------------------------------------- records
@dataclass
class AttendanceRow:
    code: str
    name: str
    designation: str | None
    zone: str | None
    manager: str | None
    asm: str | None
    status: str                          # raw Bizom status: present / late / halfday / absent
    leave: str | None                    # Privilege Leave, Weekly Off, ...
    attendance_time: str | None
    first_activity: str | None
    last_activity: str | None
    market_minutes: int | None
    km: float | None
    end_time: str | None
    variance_m: float | None
    photo: bool | None
    active: bool


@dataclass
class EodRow:
    name: str
    marked: bool
    attendance_time: str | None
    eod_time: str | None


@dataclass
class CallSummary:
    calls: int = 0
    productive: int = 0
    short: int = 0                       # under the short-call limit (seconds)
    telephonic: int = 0
    beat_jump: int = 0
    far: int = 0                         # further from the outlet than the limit
    max_distance_m: float = 0.0
    fast_moves: int = 0                  # consecutive calls needing an impossible speed
    outside_hours: int = 0
    first_call: str | None = None
    last_call: str | None = None
    order_value: float = 0.0


@dataclass
class BizomFile:
    kind: str
    report_date: date
    attendance: list[AttendanceRow] = field(default_factory=list)
    eod: list[EodRow] = field(default_factory=list)
    calls: dict[str, CallSummary] = field(default_factory=dict)
    skipped: int = 0                     # rows without a usable code / name


def _single_date(values: list[date | None], label: str) -> date:
    ds = {d for d in values if d}
    if not ds:
        raise BizomError(f"{label}: no date found.")
    if len(ds) > 1:
        raise BizomError(f"{label}: the file covers {len(ds)} dates ({min(ds):%d-%b} to {max(ds):%d-%b}); export one day at a time.")
    return ds.pop()


def parse(rows: list[list[str]], short_call_seconds: int = 60, far_call_m: float = 100, max_speed_kmh: float = 60,
          day_end: str = "21:00") -> BizomFile:
    found = _header(rows)
    if found is None:
        raise BizomError("Not a Bizom Attendance, Attendance & EOD or Call Variance report (columns not recognised).")
    at, kind, col = found
    body = [r for r in rows[at + 1:] if any(_clean(c) for c in r)]
    g = lambda r, name: _clean(r[col[name]]) if name in col and col[name] < len(r) else ""  # noqa: E731

    if kind == ATTENDANCE:
        d = _single_date([_date(g(r, "date")) for r in body], LABEL[kind])
        out, skipped = [], 0
        for r in body:
            code = norm_code(g(r, "emp id"))
            if not re.match(r"^[A-Z]{2}\d{3,}$", code):          # vacant / test users and bad codes ('ASM')
                skipped += 1
                continue
            photo = g(r, "photograph status").lower()
            out.append(AttendanceRow(
                code=code, name=g(r, "emp name"), designation=g(r, "emp designation") or None, zone=g(r, "zone") or None,
                manager=g(r, "reporting_manager") or None, asm=g(r, "asm/rsm") or None, status=g(r, "status").lower(),
                leave=g(r, "leave details") or None, attendance_time=hhmm(g(r, "attendance time")),
                first_activity=hhmm(g(r, "first transaction time")), last_activity=hhmm(g(r, "last transaction time")),
                market_minutes=(s // 60 if (s := seconds(g(r, "time spent in market"))) is not None else None),
                km=_num(g(r, "km_traveled")), end_time=hhmm(g(r, "end time")), variance_m=_num(g(r, "variance(metres)")),
                photo=None if not photo else photo == "yes", active=g(r, "user_status").lower() != "inactive"))
        return BizomFile(kind, d, attendance=out, skipped=skipped)

    if kind == EOD:
        d = _single_date([_date(g(r, "for_date")) for r in body], LABEL[kind])
        out = [EodRow(name=g(r, "user_name"), marked=g(r, "status").lower() == "marked", attendance_time=hhmm(g(r, "attendance_time")),
                      eod_time=hhmm(g(r, "eod_time"))) for r in body if g(r, "user_name")]
        return BizomFile(kind, d, eod=out, skipped=len(body) - len(out))

    # CALLS: aggregate per person; coordinates only used here, in memory
    d = _single_date([_date(g(r, "call_start_date")) for r in body], LABEL[kind])
    by: dict[str, list] = defaultdict(list)
    skipped = 0
    for r in body:
        code = norm_code(g(r, "emp_id") or g(r, "user_name"))
        if not re.match(r"^[A-Z]{2}\d{3,}$", code):
            skipped += 1
            continue
        by[code].append(r)
    summaries: dict[str, CallSummary] = {}
    end_m = minutes_of(day_end)
    for code, rs in by.items():
        s = CallSummary()
        calls = []
        for r in rs:
            start, end = hhmm(g(r, "call_start_time")), hhmm(g(r, "call_end_time"))
            dur, dist = seconds(g(r, "total_time_spent")), _num(g(r, "distance_variance(mtrs)"))
            lat, lon = _num(g(r, "call_latitude")), _num(g(r, "call_longitude"))
            s.calls += 1
            s.productive += g(r, "call_status").upper() == "PC"
            s.short += dur is not None and dur < short_call_seconds
            s.telephonic += g(r, "order_type").lower() == "telephonic"
            s.beat_jump += "beat_jump" in g(r, "reason_category_name").lower()
            if dist is not None:
                s.far += dist > far_call_m
                s.max_distance_m = max(s.max_distance_m, dist)
            if start and end_m is not None and minutes_of(start) >= end_m:
                s.outside_hours += 1
            s.order_value += _num(g(r, "order_value")) or 0.0
            if start:
                calls.append((start, end or start, lat, lon))
        calls.sort()
        if calls:
            s.first_call, s.last_call = calls[0][0], max(c[1] for c in calls)
        for (a_s, a_e, la1, lo1), (b_s, _b_e, la2, lo2) in zip(calls, calls[1:]):
            if None in (la1, lo1, la2, lo2):
                continue
            km = _haversine(la1, lo1, la2, lo2)
            gap_h = max(1, minutes_of(b_s) - minutes_of(a_e)) / 60
            if km > 1 and km / gap_h > max_speed_kmh:
                s.fast_moves += 1
        summaries[code] = s
    return BizomFile(kind, d, calls=summaries, skipped=skipped)


def read_rows(data: bytes, filename: str) -> list[list[str]]:
    """Bizom exports standard comma CSV (every value quoted); Excel copies are read with the shared reader."""
    import csv
    import io

    from ingestion.file_reader import ReadError, read_raw

    name = filename.lower()
    if name.endswith(".csv"):
        for enc in ("utf-8-sig", "cp1252"):
            try:
                text = data.decode(enc)
                break
            except UnicodeDecodeError:
                continue
        else:
            raise BizomError(f"{filename}: the file's text encoding is not supported; save it as UTF-8 CSV.")
        return [[c.strip() for c in r] for r in csv.reader(io.StringIO(text))]
    if name.endswith(".xlsx"):
        try:
            return read_raw(data, "xlsx")[0]
        except ReadError as exc:
            raise BizomError(f"{filename}: {exc}") from exc
    raise BizomError(f"{filename}: upload the Bizom report as .csv or .xlsx.")


def _haversine(la1: float, lo1: float, la2: float, lo2: float) -> float:
    p1, p2, dl = math.radians(la1), math.radians(la2), math.radians(lo2 - lo1)
    a = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 6371 * 2 * math.asin(math.sqrt(a))
