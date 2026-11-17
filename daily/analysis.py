"""Turns one day's Pocket HRMS AttendanceSummary into statuses, insights and highlights.

Statuses (how each is decided is in Settings -> Counting rules):
  PRESENT        two or more punches
  MISSING_PUNCH  exactly one punch (counted present unless the rule says otherwise)
  ON_DUTY        a Type code listed as on duty (e.g. LD)
  WFH            a Type code listed as work from home (counts as present)
  HALF_DAY       leave with a half-day portion
  LEAVE          any other Type code (PL, SL, ...)
  ABSENT         no punch (per rule)
  NOT_TRACKED    no punch and "Shift Not Assigned" (per rule) -- left out of attendance %
  WEEK_OFF       Type = WO (week off) -- left out of attendance %

The Pocket HRMS Permission Report (short-leave permissions) is applied by EMP_CODE: an APPROVED
permission excuses a late arrival / early leaving inside its time window; a PENDING one is shown but
excuses nothing. Pocket HRMS is the only attendance source.
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field
from datetime import date, datetime

from core.config import Rules

STATUSES = ["PRESENT", "MISSING_PUNCH", "ON_DUTY", "WFH", "HALF_DAY", "LEAVE", "ABSENT", "WEEK_OFF", "NOT_TRACKED"]
STATUS_LABEL = {"PRESENT": "Present", "MISSING_PUNCH": "Missing punch", "ON_DUTY": "On duty", "WFH": "Work from home", "HALF_DAY": "Half day",
                "LEAVE": "Leave", "ABSENT": "Absent", "WEEK_OFF": "Week off", "NOT_TRACKED": "Not tracked"}
UNCOUNTED = ("NOT_TRACKED", "WEEK_OFF")       # left out of attendance %
HRMS = "HRMS"
PERMISSION_GRACE_MIN = 15          # arrival/leaving up to 15 min outside the permission window is still covered
NO_SHIFT = "shift not assigned"
HOD_PREFIX = "HOD:"
NOT_IN_MASTER = "Not in employee master"


def hod_scope(name: str) -> str:
    return f"{HOD_PREFIX}{name}"


def in_scope(scope: str, category: str, hod: str | None) -> bool:
    if scope == "ALL":
        return True
    if scope.startswith(HOD_PREFIX):
        return hod == scope[len(HOD_PREFIX):]
    return category == scope


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
    department: str | None = None      # from the employee master (None = not in master)
    hod: str | None = None
    team: str | None = None
    manager: str | None = None
    source: str = "HRMS"
    permission: str | None = None      # e.g. "Approved 16:00-18:00" / "Pending 16:00-18:00"


def _minutes(hhmm: str | None) -> int | None:
    if not hhmm:
        return None
    parts = hhmm.split(":")
    return int(parts[0]) * 60 + int(parts[1])


def _hhmm(minutes: float | None) -> str | None:
    """Minutes after midnight -> 12-hour display time, e.g. 545 -> "9:05 AM"."""
    if minutes is None:
        return None
    m = int(round(minutes)) % (24 * 60)
    h = m // 60
    return f"{h % 12 or 12}:{m % 60:02d} {'AM' if h < 12 else 'PM'}"


def mins_hm(minutes: float | None) -> str | None:
    """Minutes -> "h:mm" (37 -> "0:37", 80 -> "1:20"); None / 0 -> None. Durations are always shown as time, not minutes."""
    if not minutes:
        return None
    m = int(round(float(minutes)))
    return f"{m // 60}:{m % 60:02d}"


def hm(hours: float | None) -> str | None:
    """Decimal hours -> "h:mm" (9.47 -> "9:28"). Everything shown to people uses hours:minutes."""
    if hours is None or hours == "":
        return None
    try:
        m = int(round(float(hours) * 60))
    except (TypeError, ValueError):
        return str(hours)
    return f"{m // 60}:{m % 60:02d}"


def t12(value: str | None) -> str | None:
    """Stored 24-hour "HH:MM" -> 12-hour display "h:MM AM/PM" (everything shown to people uses 12-hour time)."""
    if not value:
        return value
    try:
        return _hhmm(_minutes(value))
    except (ValueError, TypeError, IndexError):
        return value


def parse_date(value: str) -> date:
    for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y", "%d-%b-%Y", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(value.strip(), fmt).date()
        except ValueError:
            continue
    raise FileError(f"Unrecognised date '{value}'.")


def apply_permissions(results: list[EmployeeResult], perm_day, report_date: date, rules: Rules) -> dict:
    """Apply the day's short-leave permissions (``daily.permissions.PermissionDay``). Returns counts."""
    from daily.permissions import APPROVED, PENDING

    todays = [p for p in perm_day.permissions if p.day == report_date]
    stats = {"rows": len(perm_day.permissions), "today": len(todays), "approved": 0, "pending": 0, "other_dates": 0,
             "excused_late": 0, "excused_early": 0, "not_in_file": 0}
    stats["other_dates"] = stats["rows"] - stats["today"]
    by_code = {r.code.upper(): r for r in results}
    late_after, early_before = late_threshold(rules), _minutes(rules.early_before)
    for perm in todays:
        r = by_code.get(perm.code)
        if r is None:
            stats["not_in_file"] += 1
            continue
        if perm.status not in (APPROVED, PENDING):
            continue
        label = f"{'Approved' if perm.status == APPROVED else 'Pending'} {perm.window}"
        r.permission = f"{r.permission}; {label}" if r.permission else label
        if perm.status == PENDING:
            stats["pending"] += 1
            if "PERMISSION_PENDING" not in r.flags:
                r.flags.append("PERMISSION_PENDING")
            continue
        stats["approved"] += 1
        start, end = _minutes(perm.start), _minutes(perm.end)
        excused = False
        if "LATE" in r.flags and start <= late_after + PERMISSION_GRACE_MIN and _minutes(r.in_time) <= end + PERMISSION_GRACE_MIN:
            r.flags.remove("LATE")
            r.late_minutes = 0
            stats["excused_late"] += 1
            excused = True
        if "LEFT_EARLY" in r.flags and end >= early_before - PERMISSION_GRACE_MIN and _minutes(r.out_time) >= start - PERMISSION_GRACE_MIN:
            r.flags.remove("LEFT_EARLY")
            r.early_minutes = 0
            stats["excused_early"] += 1
            excused = True
        if excused and "SHORT_HOURS" in r.flags:
            r.flags.remove("SHORT_HOURS")
        if "PERMISSION" not in r.flags:
            r.flags.append("PERMISSION")
    return stats


def report_date_of(rows: list[dict]) -> date:
    if not rows:
        raise FileError("The file has no employee rows.")
    dates = Counter(r["Date"] for r in rows if r.get("Date"))
    if not dates:
        raise FileError("No dates found in the file.")
    if len(dates) > 1:
        raise FileError(f"The file contains {len(dates)} different dates; upload one day at a time.")
    return parse_date(next(iter(dates)))


def late_threshold(rules: Rules) -> int:
    """Minutes after midnight after which a first punch is late: the latest punch-in (flexi_until) if set,
    else the office opening time (late_after)."""
    return _minutes(rules.flexi_until or rules.late_after)


def classify(rows: list[dict], rules: Rules) -> tuple[date, list[EmployeeResult], int]:
    """Rows from the reshaped AttendanceSummary -> (report date, results, excluded count)."""
    report_date = report_date_of(rows)

    excludes = [re.compile(p, re.IGNORECASE) for p in rules.exclude_codes]
    on_duty = {c.strip().upper() for c in rules.on_duty_codes}
    wfh = {c.strip().upper() for c in rules.wfh_codes}
    late_after, early_before = late_threshold(rules), _minutes(rules.early_before)
    office_opens = _minutes(rules.late_after) if rules.flexi_until else None
    always_present = {c.strip().upper() for c in rules.always_present_codes if c.strip()}
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
        elif (leave and leave in wfh) or (r.get("WFH Remark") and not leave):
            status = "WFH"
        elif leave in ("WO", "W/O", "WEEKOFF", "WEEK OFF"):
            status = "WEEK_OFF"
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
                             leave_type=leave or None, day_portion=portion,
                             status=status, department=(r.get("Department") or None))
        need = round(rules.min_work_hours * 60)
        if in_t and status in ("PRESENT", "MISSING_PUNCH"):
            if _minutes(in_t) > late_after:
                res.late_minutes = _minutes(in_t) - late_after        # counted from the latest allowed punch-in
                res.flags.append("LATE")
            elif office_opens is not None and _minutes(in_t) > office_opens:
                res.flags.append("FLEXI")                           # came in the flexible window: on time
        if out_t and status == "PRESENT" and _minutes(out_t) < early_before and (work is None or work < need):
            # left before office close WITHOUT completing the required hours (counted from their own punch-in)
            res.early_minutes = min(early_before - _minutes(out_t), need - work if work is not None else early_before)
            res.flags.append("LEFT_EARLY")
        if work is not None and work < rules.min_work_hours * 60:
            res.flags.append("SHORT_HOURS")
        if work is not None and work > rules.long_work_hours * 60:
            res.flags.append("LONG_HOURS")
        if status == "MISSING_PUNCH":
            res.flags.append("MISSING_PUNCH")
        if code.upper() in always_present:
            if res.status in ("ABSENT", "MISSING_PUNCH", "NOT_TRACKED"):
                res.status = "PRESENT"
            res.flags = ["ALWAYS_PRESENT"]                 # never late / left early / short hours / missing punch
            res.late_minutes = res.early_minutes = 0
        results.append(res)
    if not results:
        raise FileError("Every row was excluded; check the exclusion list in Settings.")
    return report_date, results, excluded


# ---------------------------------------------------------------------------- insights
def _present_equivalent(c: Counter, rules: Rules) -> float:
    return (c["PRESENT"] + c["ON_DUTY"] + c["WFH"] + (c["MISSING_PUNCH"] if rules.single_punch_counts_present else 0)
            + 0.5 * c["HALF_DAY"])


def summarize(results: list[EmployeeResult], rules: Rules) -> dict:
    c = Counter(r.status for r in results)
    tracked = len(results) - sum(c[s] for s in UNCOUNTED)
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
        buckets.append({"label": f"{_hhmm(b)} - {_hhmm(b + 30)}", "count": sum(1 for m in ins if b <= m < b + 30)})
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
        rule = f"punch-in after {t12(rules.flexi_until or rules.late_after)}"
        out.append({"kind": "warn", "text": f"{s['late']} late arrivals ({rule}; {s['late_pct']}% of those who came in), "
                                            f"on average {mins_hm(s['avg_late_minutes']) or '0:00'} hrs late; latest in at {s['latest_in']}."})
    elif s["avg_in_time"]:
        out.append({"kind": "good", "text": f"No late arrivals; average arrival {s['avg_in_time']}."})
    if c["MISSING_PUNCH"]:
        out.append({"kind": "warn", "text": f"{c['MISSING_PUNCH']} employee(s) punched only once (missing punch) - please regularise."})
    if s["left_early"]:
        out.append({"kind": "warn", "text": f"{s['left_early']} left before {t12(rules.early_before)} without completing {rules.min_work_hours:g} h."})
    if s["avg_work_hours"] is not None:
        out.append({"kind": "info", "text": f"Average working time {hm(s['avg_work_hours'])} (h:mm); {s['short_hours']} worked less than "
                                            f"{rules.min_work_hours:g} h, {s['long_hours']} more than {rules.long_work_hours:g} h."})
    if c["LEAVE"] or c["ON_DUTY"] or c["HALF_DAY"] or c["WFH"]:
        out.append({"kind": "info", "text": f"{c['LEAVE']} on leave, {c['HALF_DAY']} half day, {c['ON_DUTY']} on duty"
                                            + (f", {c['WFH']} working from home" if c["WFH"] else "") + "."})
    if c["WEEK_OFF"]:
        out.append({"kind": "info", "text": f"{c['WEEK_OFF']} on week off; not counted in attendance %."})
    if c["NOT_TRACKED"]:
        biggest = max(by_category.items(), key=lambda kv: kv[1]["counts"]["NOT_TRACKED"])[0] if by_category else ""
        out.append({"kind": "info", "text": f"{c['NOT_TRACKED']} employee(s) not tracked (no punch, no shift assigned)"
                                            + (f", mostly {biggest}" if len(by_category) > 1 else "") + "; not counted in attendance %."})
    return out


def _breakdown_row(name: str, s: dict, hod: str | None = None) -> dict:
    c = s["counts"]
    return {"name": name, "hod": hod, "employees": s["employees"], "tracked": s["tracked"],
            "attendance_pct": s["attendance_pct"], "present": c["PRESENT"] + c["ON_DUTY"] + c["WFH"] + c["MISSING_PUNCH"],
            "absent": c["ABSENT"], "late": s["late"], "leave": c["LEAVE"] + c["HALF_DAY"],
            "not_tracked": c["NOT_TRACKED"] + c["WEEK_OFF"]}


def _group(results: list[EmployeeResult], key) -> dict[str, list[EmployeeResult]]:
    out: dict[str, list[EmployeeResult]] = defaultdict(list)
    for r in results:
        out[key(r)].append(r)
    return dict(sorted(out.items()))


def _scope_data(rows: list[EmployeeResult], rules: Rules, previous: dict | None, label: str, use_master: bool,
                prefer: str) -> dict:
    """Summary, highlights, arrivals and a breakdown table for one audience."""
    s = summarize(rows, rules)
    if use_master and prefer == "department":
        groups, by = _group(rows, lambda r: r.department or NOT_IN_MASTER), "Department"
        if len(groups) == 1:          # a HOD with one department: show their teams instead
            groups, by = _group(rows, lambda r: r.team or NOT_IN_MASTER), "Team"
    else:
        groups, by = _group(rows, lambda r: r.category), "Category"
    sums = {k: summarize(v, rules) for k, v in groups.items()}
    hod_of = {k: Counter(r.hod for r in v if r.hod).most_common(1)[0][0] if any(r.hod for r in v) else None
              for k, v in groups.items()} if by == "Department" else {}
    return {"summary": s,
            "highlights": highlights(s, sums if len(sums) > 1 else {}, rules, previous, label),
            "arrivals": in_time_buckets(rows),
            "breakdown": {"by": by, "rows": [_breakdown_row(k, v, hod_of.get(k)) for k, v in sums.items()] if len(sums) > 1 else []}}


def build_insights(report_date: date, results: list[EmployeeResult], rules: Rules, excluded: int,
                   previous: dict | None = None, master: dict | None = None, sources: dict | None = None) -> dict:
    """All numbers for one day: ALL, every Category and every HOD. `previous` = the prior day's insights.
    `master` = counts from matching the employee master (None when no master is loaded)."""
    prev_scopes = (previous or {}).get("scopes", {})
    use_master = bool(master and master.get("matched"))
    by_cat_rows = _group(results, lambda r: r.category)
    by_category = {cat: summarize(rows, rules) for cat, rows in by_cat_rows.items()}

    def prev_of(scope: str) -> dict | None:
        return prev_scopes.get(scope, {}).get("summary")

    scopes = {"ALL": _scope_data(results, rules, prev_of("ALL"), "All", use_master, "department")}
    if master:
        extra = []
        if master.get("not_in_master"):
            extra.append({"kind": "warn", "text": f"{master['not_in_master']} employee(s) in the attendance file are not in the "
                                                  f"employee master - add them on the Employees screen so their HOD gets them."})
        if master.get("out_of_scope"):
            extra.append({"kind": "info", "text": f"{master['out_of_scope']} field staff who are not in the employee master were "
                                                  f"left out (their attendance is handled by the Bizom tool)."})
        if master.get("missing_from_file"):
            extra.append({"kind": "info", "text": f"{master['missing_from_file']} active employee(s) in the master are not in "
                                                  f"the attendance file of {report_date:%d-%b-%Y}."})
        scopes["ALL"]["highlights"] += extra
    pm = (sources or {}).get("permissions")
    if pm and pm["today"]:
        excused = pm["excused_late"] + pm["excused_early"]
        scopes["ALL"]["highlights"].append({"kind": "warn" if pm["pending"] else "info", "text": (
            f"{pm['today']} short-leave permission(s) on {report_date:%d-%b-%Y}: {pm['approved']} approved"
            + (f" (excused {excused} late / early)" if excused else "") + f", {pm['pending']} still pending approval.")})
    elif sources is not None and sources.get("hrms") and not sources.get("permission_file"):
        scopes["ALL"]["highlights"].append({"kind": "info", "text": "Permission Report not uploaded for this day - late / early "
                                                                   "arrivals are shown without permissions."})
    for cat, rows in by_cat_rows.items():
        scopes[cat] = _scope_data(rows, rules, prev_of(cat), cat, use_master, "department")
    hods = []
    if use_master:
        for hod, rows in _group([r for r in results if r.hod], lambda r: r.hod).items():
            key = hod_scope(hod)
            scopes[key] = _scope_data(rows, rules, prev_of(key), hod, True, "department")
            hods.append({"name": hod, "scope": key, "employees": len(rows),
                         "departments": sorted({r.department for r in rows if r.department}),
                         "attendance_pct": scopes[key]["summary"]["attendance_pct"]})
    by_department = ({k: summarize(v, rules) for k, v in _group(results, lambda r: r.department or NOT_IN_MASTER).items()}
                     if use_master else {})
    return {
        "report_date": report_date.isoformat(),
        "excluded": excluded,
        "categories": sorted(by_cat_rows),
        "by_category": by_category,
        "departments": sorted(by_department),
        "by_department": by_department,
        "hods": hods,
        "master": master,
        "sources": sources or {"hrms": True},
        "scopes": scopes,
        "previous_date": (previous or {}).get("report_date"),
        "rules": rules.model_dump(),
    }


def result_to_dict(r: EmployeeResult) -> dict:
    d = asdict(r)
    d["status_label"] = STATUS_LABEL[r.status]
    d["work_hours"] = round(r.work_minutes / 60, 2) if r.work_minutes is not None else None
    return d
