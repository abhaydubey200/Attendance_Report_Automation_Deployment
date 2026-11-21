"""Read the three Bizom exports. Each file is recognised by its columns, one day per file.

* Attendance report      - one row per user who MARKED attendance: status, times, time in market, KM, manager names.
* Attendance & EOD report - every active user, "Marked" / "Not Marked", end-of-day time. Names only (no code).
* Call Variance report   - one row per outlet visit: times, call + outlet location, beat, productive or not, order value.
* Attendance history     - Bizom's multi-day "AttendanceReport" export: attendance location and phone (IMEI) per day.

Kept for the location checks (decided 2026-11-21, deleted after 6 months): attendance / day-end / call / outlet coordinates,
attendance photo links, and the phone's IMEI only as a scrambled code (see sales.geo.device_code). Never kept: phone
numbers, outlet mobiles, addresses.
"""

from __future__ import annotations

import math
import re
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime

ATTENDANCE, EOD, CALLS, HISTORY, CLAIMS = "ATTENDANCE", "EOD", "CALLS", "HISTORY", "CLAIMS"
LABEL = {ATTENDANCE: "Bizom Attendance report", EOD: "Bizom Attendance & EOD report", CALLS: "Bizom Call Variance report",
         HISTORY: "Bizom Attendance history (AttendanceReport, many days)", CLAIMS: "Bizom Claim report"}


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


_HREF = re.compile(r"""(https?://[^\s'"<>]+)""")


def photo_link(v: str) -> str | None:
    """'<a href='https://...jpg'>..' or a bare URL -> the URL; 'No Image' / blank -> None."""
    m = _HREF.search(v or "")
    return m.group(1)[:500] if m else None


def latlng(v: str) -> tuple[float, float] | None:
    """'28.6139,77.2090' -> (28.6139, 77.209). Rejects 0,0 and values outside India's rough box."""
    parts = [p for p in re.split(r"[,\s]+", _clean(v)) if p]
    if len(parts) != 2:
        return None
    try:
        la, lo = float(parts[0]), float(parts[1])
    except ValueError:
        return None
    return (la, lo) if 5 <= la <= 38 and 66 <= lo <= 99 else None


def coord(la: float | None, lo: float | None) -> tuple[float, float] | None:
    return (la, lo) if la is not None and lo is not None and 5 <= la <= 38 and 66 <= lo <= 99 else None


# ---------------------------------------------------------------- recognising a file
_SIGNATURE = {
    ATTENDANCE: {"emp id", "status", "attendance time", "time spent in market"},
    EOD: {"user_name", "for_date", "eod_time", "status"},
    CALLS: {"call_id", "call_start_time", "distance_variance(mtrs)"},
    HISTORY: {"emp id", "for date", "attendance time", "imei"},
    CLAIMS: {"claimdetail_id", "claim_date", "claim_type", "claim_amount", "employee_code"},
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
    photo_url: str | None = None
    location: tuple[float, float] | None = None


@dataclass
class EodRow:
    name: str
    marked: bool
    attendance_time: str | None
    eod_time: str | None
    location: tuple[float, float] | None = None       # where attendance was marked
    eod_location: tuple[float, float] | None = None   # where the day was ended
    photo_url: str | None = None


@dataclass
class CallPoint:
    call_id: str
    start: str | None
    end: str | None
    duration_s: int | None
    location: tuple[float, float] | None
    outlet_id: str | None
    beat_id: str | None
    beat_name: str | None
    distance_m: float | None              # Bizom's own figure
    productive: bool


@dataclass
class Outlet:
    outlet_id: str
    name: str
    beat_id: str | None
    beat_name: str | None
    category: str | None
    pincode: str | None
    location: tuple[float, float] | None


@dataclass
class HistoryRow:
    code: str
    day: date
    attendance_time: str | None
    location: tuple[float, float] | None
    imei: str | None                      # raw only in memory; stored scrambled
    status: str | None = None             # present / late / halfday / absent / leave / week_off / not_marked
    leave: str | None = None


@dataclass
class ClaimRow:
    detail_id: str
    claim_id: str | None
    code: str
    name: str
    designation: str | None
    day: date
    submit_date: date | None
    claim_type: str                       # as in Bizom, cleaned
    present_type: str | None              # Retailing HQ / Retailing EX-HQ / Joint Working ...
    mode: str | None
    from_place: str | None
    to_place: str | None
    amount: float
    approved_amount: float | None
    approval_status: str | None
    approver: str | None
    document: str | None
    bill_1: str | None
    bill_2: str | None
    odometer_start: str | None
    odometer_end: str | None
    calls: int | None                     # TC that day
    orders: int | None                    # PC
    sales_value: float | None
    market_minutes: int | None


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
    call_points: dict[str, list[CallPoint]] = field(default_factory=dict)
    outlets: dict[str, Outlet] = field(default_factory=dict)
    history: list[HistoryRow] = field(default_factory=list)
    claims: list[ClaimRow] = field(default_factory=list)
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
    raw = lambda r, name: r[col[name]] if name in col and col[name] < len(r) else ""  # noqa: E731

    if kind == CLAIMS:                    # many days: one row per claim line
        out, skipped = [], 0
        for r in body:
            code, d = norm_code(g(r, "employee_code")), _date(g(r, "claim_date"))
            did = g(r, "claimdetail_id")
            if not re.match(r"^[A-Z]{2}\d{3,}$", code) or d is None or not did:
                skipped += 1
                continue
            num = lambda name: _num(g(r, name))  # noqa: E731
            appr = num("level_2_approved_amount") if g(r, "l2_approval_status").lower() == "approved" else num("level_1_approved_amount")
            out.append(ClaimRow(
                detail_id=did[:40], claim_id=g(r, "claim_id")[:40] or None, code=code, name=g(r, "user_name")[:200],
                designation=g(r, "designation")[:60] or None, day=d, submit_date=_date(g(r, "claim submit date")),
                claim_type=re.sub(r"\s+", " ", re.sub(r"[^\w&+()/ -]", "-", g(r, "claim_type"))).strip()[:100],
                present_type=g(r, "present_type")[:60] or None, mode=g(r, "mode of travel").strip(".")[:40] or None,
                from_place=g(r, "from_place")[:120] or None, to_place=g(r, "to_place")[:120] or None, amount=num("claim_amount") or 0.0,
                approved_amount=appr, approval_status=g(r, "claim_approval_status")[:60] or None,
                approver=g(r, "first_level_approver")[:120] or None, document=photo_link(raw(r, "document")),
                bill_1=photo_link(raw(r, "bill_image 1")), bill_2=photo_link(raw(r, "bill_image 2")),
                odometer_start=photo_link(raw(r, "odometer image of start")), odometer_end=photo_link(raw(r, "odometer image of end")),
                calls=int(num("tc")) if num("tc") is not None else None, orders=int(num("pc")) if num("pc") is not None else None,
                sales_value=num("total secondary value"),
                market_minutes=(s // 60 if (s := seconds(g(r, "time_spent_in_market"))) is not None else None)))
        if not out:
            raise BizomError(f"{LABEL[kind]}: no claim rows with an employee code and claim date.")
        return BizomFile(kind, max(c.day for c in out), claims=out, skipped=skipped)

    if kind == HISTORY:                   # many days: attendance location + phone per person per day
        out, skipped, dates = [], 0, set()
        for r in body:
            code, d = norm_code(g(r, "emp id")), _date(g(r, "for date"))
            if not re.match(r"^[A-Z]{2}\d{3,}$", code) or d is None:
                skipped += 1
                continue
            dates.add(d)
            att, leave, marked = g(r, "attendance").lower(), g(r, "leave details"), g(r, "status").lower()
            st = ("week_off" if leave.lower().startswith("weekly off") else "leave" if leave else
                  att if att in ("present", "late", "halfday", "absent") else "not_marked" if marked == "not marked" else None)
            out.append(HistoryRow(code, d, hhmm(g(r, "attendance time")), latlng(g(r, "location")), g(r, "imei") or None, st,
                                  leave.replace("Causal", "Casual") or None))
        if not out:
            raise BizomError(f"{LABEL[kind]}: no rows with an employee code and date.")
        return BizomFile(kind, max(dates), history=out, skipped=skipped)

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
                photo=None if not photo else photo == "yes", active=g(r, "user_status").lower() != "inactive",
                photo_url=photo_link(raw(r, "attendance image")), location=latlng(g(r, "location"))))
        return BizomFile(kind, d, attendance=out, skipped=skipped)

    if kind == EOD:
        d = _single_date([_date(g(r, "for_date")) for r in body], LABEL[kind])
        out = [EodRow(name=g(r, "user_name"), marked=g(r, "status").lower() == "marked", attendance_time=hhmm(g(r, "attendance_time")),
                      eod_time=hhmm(g(r, "eod_time")), location=latlng(g(r, "location")), eod_location=latlng(g(r, "eod_location")),
                      photo_url=photo_link(raw(r, "attendance_image"))) for r in body if g(r, "user_name")]
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
    points: dict[str, list[CallPoint]] = {}
    outlets: dict[str, Outlet] = {}
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
            oid = g(r, "outlet_id") or None
            if oid and oid not in outlets:
                outlets[oid] = Outlet(oid, g(r, "outlet_name")[:200], g(r, "beat_id") or None, g(r, "beat_name")[:200] or None,
                                      g(r, "outlet category")[:100] or g(r, "outlet_type")[:100] or None, g(r, "outlet_pincode") or None,
                                      coord(_num(g(r, "outlet_latitude")), _num(g(r, "outlet_longitude"))))
            points.setdefault(code, []).append(CallPoint(
                g(r, "call_id")[:40], start, end, dur, coord(lat, lon), oid, g(r, "beat_id") or None, g(r, "beat_name")[:200] or None,
                dist, g(r, "call_status").upper() == "PC"))
        points[code].sort(key=lambda p: p.start or "99:99")
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
    return BizomFile(kind, d, calls=summaries, call_points=points, outlets=outlets, skipped=skipped)


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
