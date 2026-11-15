"""Turns one day's Pocket HRMS AttendanceSummary into statuses, insights and highlights.

Statuses (how each is decided is in Settings -> Counting rules):
  PRESENT        two or more punches
  MISSING_PUNCH  exactly one punch (counted present unless the rule says otherwise)
  ON_DUTY        a Type code listed as on duty (e.g. LD)
  HALF_DAY       leave with a half-day portion
  LEAVE          any other Type code (PL, SL, ...)
  ABSENT         no punch (per rule)
  NOT_TRACKED    no punch and "Shift Not Assigned" (per rule) -- left out of attendance %
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field
from datetime import date, datetime

from core.config import Rules

STATUSES = ["PRESENT", "MISSING_PUNCH", "ON_DUTY", "HALF_DAY", "LEAVE", "ABSENT", "NOT_TRACKED"]
STATUS_LABEL = {"PRESENT": "Present", "MISSING_PUNCH": "Missing punch", "ON_DUTY": "On duty", "HALF_DAY": "Half day",
                "LEAVE": "Leave", "ABSENT": "Absent", "NOT_TRACKED": "Not tracked"}
NO_SHIFT = "shift not assigned"


class FileError(ValueError):
    """The file cannot be used; the message is shown to the user."""


@dataclass
class EmployeeResult:
    code: str
    name: str
    category: str
    shift: str
    in_time: str | None
    out_time: str | None
    punches: int
    work_minutes: int | None
    leave_type: str | None
    day_portion: str | None
    status: str
    late_minutes: int = 0
    early_minutes: int = 0
    flags: list[str] = field(default_factory=list)


def _minutes(hhmm: str | None) -> int | None:
    if not hhmm:
        return None
    parts = hhmm.split(":")
    return int(parts[0]) * 60 + int(parts[1])


def _hhmm(minutes: float | None) -> str | None:
    if minutes is None:
        return None
    m = int(round(minutes))
    return f"{m // 60:02d}:{m % 60:02d}"


def parse_date(value: str) -> date:
    for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y", "%d-%b-%Y", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(value.strip(), fmt).date()
        except ValueError:
            continue
    raise FileError(f"Unrecognised date '{value}'.")


def classify(rows: list[dict], rules: Rules) -> tuple[date, list[EmployeeResult], int]:
    """Rows from the reshaped AttendanceSummary -> (report date, results, excluded count)."""
    if not rows:
        raise FileError("The file has no employee rows.")
    dates = Counter(r["Date"] for r in rows if r.get("Date"))
    if not dates:
        raise FileError("No dates found in the file.")
    if len(dates) > 1:
        raise FileError(f"The file contains {len(dates)} different dates; upload one day at a time.")
    report_date = parse_date(next(iter(dates)))

    excludes = [re.compile(p, re.IGNORECASE) for p in rules.exclude_codes]
    on_duty = {c.strip().upper() for c in rules.on_duty_codes}
    late_after, early_before = _minutes(rules.late_after), _minutes(rules.early_before)
    results, excluded = [], 0
    for r in rows:
        code = (r.get("Code") or "").strip()
        if not code or any(p.search(code) for p in excludes):
            excluded += 1
            continue
        punches = int(r.get("Punches") or 0)
        in_t, out_t = r.get("In Time") or None, r.get("Out Time") or None
        leave = (r.get("Type") or "").strip().upper() or None
        portion = (r.get("Day") or "").strip() or None
        shift = (r.get("Shift Name") or "").strip()

        if leave and leave in on_duty:
            status = "ON_DUTY"
        elif leave and portion and "half" in portion.lower():
            status = "HALF_DAY"
        elif leave:
            status = "LEAVE"
        elif punches >= 2:
            status = "PRESENT"
        elif punches == 1:
            status = "MISSING_PUNCH"
        elif shift.lower() == NO_SHIFT:
            status = rules.no_punch_no_shift
        else:
            status = rules.no_punch_with_shift

        work = None
        if in_t and out_t:
            a, b = _minutes(in_t), _minutes(out_t)
            work = b - a if b >= a else b + 24 * 60 - a       # overnight
        res = EmployeeResult(code=code, name=(r.get("Name") or "").strip(), category=(r.get("Category") or "Unassigned").strip()
                             or "Unassigned", shift=shift, in_time=in_t, out_time=out_t, punches=punches, work_minutes=work,
                             leave_type=leave, day_portion=portion, status=status)
        if in_t and status in ("PRESENT", "MISSING_PUNCH") and _minutes(in_t) > late_after:
            res.late_minutes = _minutes(in_t) - late_after
            res.flags.append("LATE")
        if out_t and status == "PRESENT" and _minutes(out_t) < early_before:
            res.early_minutes = early_before - _minutes(out_t)
            res.flags.append("LEFT_EARLY")
        if work is not None and work < rules.min_work_hours * 60:
            res.flags.append("SHORT_HOURS")
        if work is not None and work > rules.long_work_hours * 60:
            res.flags.append("LONG_HOURS")
        if status == "MISSING_PUNCH":
            res.flags.append("MISSING_PUNCH")
        results.append(res)
    if not results:
        raise FileError("Every row was excluded; check the exclusion list in Settings.")
    return report_date, results, excluded


# ---------------------------------------------------------------------------- insights
def _present_equivalent(c: Counter, rules: Rules) -> float:
    return (c["PRESENT"] + c["ON_DUTY"] + (c["MISSING_PUNCH"] if rules.single_punch_counts_present else 0)
            + 0.5 * c["HALF_DAY"])


def summarize(results: list[EmployeeResult], rules: Rules) -> dict:
    c = Counter(r.status for r in results)
    tracked = len(results) - c["NOT_TRACKED"]
    present_eq = _present_equivalent(c, rules)
    came_in = [r for r in results if r.in_time and r.status in ("PRESENT", "MISSING_PUNCH")]
    ins = [_minutes(r.in_time) for r in came_in]
    works = [r.work_minutes for r in results if r.work_minutes is not None]
    late = [r for r in results if "LATE" in r.flags]
    early = [r for r in results if "LEFT_EARLY" in r.flags]
    return {
        "employees": len(results),
        "tracked": tracked,
        "counts": {s: c.get(s, 0) for s in STATUSES},
        "attendance_pct": round(100 * present_eq / tracked, 1) if tracked else None,
        "absent_pct": round(100 * c["ABSENT"] / tracked, 1) if tracked else None,
        "late": len(late),
        "late_pct": round(100 * len(late) / len(came_in), 1) if came_in else None,
        "avg_late_minutes": round(sum(r.late_minutes for r in late) / len(late)) if late else 0,
        "left_early": len(early),
        "short_hours": sum(1 for r in results if "SHORT_HOURS" in r.flags),
        "long_hours": sum(1 for r in results if "LONG_HOURS" in r.flags),
        "avg_in_time": _hhmm(sum(ins) / len(ins)) if ins else None,
        "earliest_in": _hhmm(min(ins)) if ins else None,
        "latest_in": _hhmm(max(ins)) if ins else None,
        "avg_work_hours": round(sum(works) / len(works) / 60, 2) if works else None,
    }


def in_time_buckets(results: list[EmployeeResult]) -> list[dict]:
    """Arrivals per 30 minutes (for the arrival-time chart)."""
    ins = sorted(_minutes(r.in_time) for r in results if r.in_time and r.status in ("PRESENT", "MISSING_PUNCH"))
    if not ins:
        return []
    start = (ins[0] // 30) * 30
    end = (ins[-1] // 30) * 30
    buckets = []
    for b in range(start, end + 30, 30):
        buckets.append({"label": f"{_hhmm(b)}-{_hhmm(b + 30)}", "count": sum(1 for m in ins if b <= m < b + 30)})
    return buckets


def _fmt_delta(now: float | None, before: float | None, unit: str = "", digits: int = 1) -> str:
    if now is None or before is None:
        return ""
    d = round(now - before, digits)
    if d == 0:
        return f" (no change from previous day)"
    return f" ({'up' if d > 0 else 'down'} {abs(d):g}{unit} from previous day)"


def highlights(summary: dict, by_category: dict[str, dict], rules: Rules, previous: dict | None, scope_label: str) -> list[dict]:
    """Plain-language key points, most important first. kind: good | warn | bad | info."""
    out: list[dict] = []
    s, c = summary, summary["counts"]
    prev = previous or {}
    if s["attendance_pct"] is not None:
        kind = "good" if s["attendance_pct"] >= 90 else "warn" if s["attendance_pct"] >= 75 else "bad"
        out.append({"kind": kind, "text": f"Attendance {s['attendance_pct']}% of {s['tracked']} tracked employees"
                                          f"{_fmt_delta(s['attendance_pct'], prev.get('attendance_pct'), ' pts')}."})
    tracked_cats = {k: v for k, v in by_category.items() if v["attendance_pct"] is not None and v["tracked"] >= 3}
    if len(tracked_cats) > 1:
        low = min(tracked_cats.items(), key=lambda kv: kv[1]["attendance_pct"])
        high = max(tracked_cats.items(), key=lambda kv: kv[1]["attendance_pct"])
        if low[0] != high[0]:
            out.append({"kind": "warn" if low[1]["attendance_pct"] < 75 else "info",
                        "text": f"{low[0]} has the lowest attendance ({low[1]['attendance_pct']}%); "
                                f"{high[0]} the highest ({high[1]['attendance_pct']}%)."})
    if c["ABSENT"]:
        worst = max(by_category.items(), key=lambda kv: kv[1]["counts"]["ABSENT"]) if len(by_category) > 1 else None
        extra = f", most in {worst[0]} ({worst[1]['counts']['ABSENT']})" if worst and worst[1]["counts"]["ABSENT"] else ""
        out.append({"kind": "bad" if (s["absent_pct"] or 0) >= 10 else "warn",
                    "text": f"{c['ABSENT']} absent ({s['absent_pct']}%){extra}"
                            f"{_fmt_delta(c['ABSENT'], (prev.get('counts') or {}).get('ABSENT'), '', 0)}."})
    if s["late"]:
        out.append({"kind": "warn", "text": f"{s['late']} late arrivals after {rules.late_after} ({s['late_pct']}% of those who came in), "
                                            f"on average {s['avg_late_minutes']} min late; latest in at {s['latest_in']}."})
    elif s["avg_in_time"]:
        out.append({"kind": "good", "text": f"No late arrivals; average arrival {s['avg_in_time']}."})
    if c["MISSING_PUNCH"]:
        out.append({"kind": "warn", "text": f"{c['MISSING_PUNCH']} employee(s) punched only once (missing punch) - please regularise."})
    if s["left_early"]:
        out.append({"kind": "warn", "text": f"{s['left_early']} left before {rules.early_before}."})
    if s["avg_work_hours"] is not None:
        out.append({"kind": "info", "text": f"Average working time {s['avg_work_hours']} h; {s['short_hours']} worked less than "
                                            f"{rules.min_work_hours:g} h, {s['long_hours']} more than {rules.long_work_hours:g} h."})
    if c["LEAVE"] or c["ON_DUTY"] or c["HALF_DAY"]:
        out.append({"kind": "info", "text": f"{c['LEAVE']} on leave, {c['HALF_DAY']} half day, {c['ON_DUTY']} on duty."})
    if c["NOT_TRACKED"]:
        biggest = max(by_category.items(), key=lambda kv: kv[1]["counts"]["NOT_TRACKED"])[0] if by_category else ""
        out.append({"kind": "info", "text": f"{c['NOT_TRACKED']} employee(s) not tracked (no punch, no shift assigned)"
                                            + (f", mostly {biggest}" if len(by_category) > 1 else "") + "; not counted in attendance %."})
    return out


def build_insights(report_date: date, results: list[EmployeeResult], rules: Rules, excluded: int,
                   previous: dict | None = None) -> dict:
    """All numbers for one day, for ALL and for every category. `previous` = the prior day's insights."""
    by_cat_rows: dict[str, list[EmployeeResult]] = defaultdict(list)
    for r in results:
        by_cat_rows[r.category].append(r)
    by_category = {cat: summarize(rows, rules) for cat, rows in sorted(by_cat_rows.items())}
    overall = summarize(results, rules)
    scopes = {"ALL": {"summary": overall, "highlights": highlights(overall, by_category, rules,
                                                                   (previous or {}).get("scopes", {}).get("ALL", {}).get("summary"), "All"),
                      "arrivals": in_time_buckets(results)}}
    for cat, rows in by_cat_rows.items():
        prev_cat = (previous or {}).get("scopes", {}).get(cat, {}).get("summary")
        scopes[cat] = {"summary": by_category[cat], "highlights": highlights(by_category[cat], {}, rules, prev_cat, cat),
                       "arrivals": in_time_buckets(rows)}
    return {
        "report_date": report_date.isoformat(),
        "excluded": excluded,
        "categories": sorted(by_cat_rows),
        "by_category": by_category,
        "scopes": scopes,
        "previous_date": (previous or {}).get("report_date"),
        "rules": rules.model_dump(),
    }


def result_to_dict(r: EmployeeResult) -> dict:
    d = asdict(r)
    d["status_label"] = STATUS_LABEL[r.status]
    d["work_hours"] = round(r.work_minutes / 60, 2) if r.work_minutes is not None else None
    return d
