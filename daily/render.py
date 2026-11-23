"""Renders the interactive HTML dashboard and the email (HTML + plain text)."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from daily.analysis import HOD_PREFIX, hm, in_scope, mins_hm, t12
from daily.branding import logo_data_uri
from jinja2 import Environment, FileSystemLoader, select_autoescape

_env = Environment(loader=FileSystemLoader(Path(__file__).parent / "templates"), autoescape=select_autoescape(["html"]))
KIND_COLORS = {"good": "#2e7d4f", "warn": "#c88a00", "bad": "#a52a1a", "info": "#d7ad5f"}


def scope_label(scope: str) -> str:
    if scope == "ALL":
        return "All employees"
    if scope.startswith(HOD_PREFIX):
        return f"HOD {scope[len(HOD_PREFIX):]}"
    return scope


def sources_label(insights: dict) -> str:
    src = insights.get("sources") or {"hrms": True}
    if src.get("bizom_file"):                   # days analysed while Bizom was still used
        return "Pocket HRMS + Bizom"
    extra = [x for x, k in (("permissions", "permission_file"), ("on duty", "onduty_file")) if src.get(k)]
    return f"Pocket HRMS (attendance + {' + '.join(extra)})" if extra else "Pocket HRMS"


def scoped_rows(rows: list[dict], scope: str) -> list[dict]:
    return [r for r in rows if in_scope(scope, r["category"], r.get("hod") or None)]


def file_stem(report_date: date, scope: str) -> str:
    safe = "".join(ch if ch.isalnum() else "_" for ch in scope_label(scope)).strip("_")
    return f"Attendance_{report_date:%Y-%m-%d}_{safe}"


def breakdown(insights: dict, scope: str) -> dict:
    """{'by': 'Department'|'Team'|'Category', 'rows': [...]}; empty rows when there is nothing to compare."""
    saved = insights["scopes"][scope].get("breakdown")
    if saved is not None:
        return saved
    rows = []      # days analysed before the employee master existed
    if scope == "ALL" and len(insights["by_category"]) > 1:
        for k, v in insights["by_category"].items():
            c = v["counts"]
            rows.append({"name": k, "hod": None, "employees": v["employees"], "tracked": v["tracked"],
                         "attendance_pct": v["attendance_pct"], "present": c["PRESENT"] + c["ON_DUTY"] + c["MISSING_PUNCH"],
                         "absent": c["ABSENT"], "late": v["late"], "leave": c["LEAVE"] + c["HALF_DAY"],
                         "not_tracked": c["NOT_TRACKED"]})
    return {"by": "Category", "rows": rows}


# ---------------------------------------------------------------------------- dashboard view
# Each person falls in exactly ONE bucket (the ring chart adds up to the team size). Late arrivals, early leavers and
# short leave are PRESENT (they count as present everywhere); they get their own cards on top, marked "counted present".
BUCKETS = [  # key, label, note, colour (ring / accent), icon
    ("present", "Present", None, "#16a34a", "check"),
    ("absent", "Absent", None, "#dc2626", "user-x"),
    ("missing", "Missing punch", None, "#7c3aed", "scan"),
    ("wfh", "Work from home", None, "#4f46e5", "laptop"),
    ("od", "On duty", None, "#0d9488", "briefcase"),
    ("leave", "On leave", None, "#64748b", "calendar"),
    ("no_record", "No record", None, "#9ca3af", "help"),
    ("not_counted", "Not counted", "week off / holiday / no shift", "#94a3b8", "minus"),
]
ALWAYS_CARDS = ("present", "absent", "late", "missing")
_BUCKET = {b[0]: b for b in BUCKETS}
FLAG_CARDS = [  # key, label, colour, icon, filter, test - people inside "present" (or missing punch), shown separately
    ("late", "Late arrival", "#d97706", "clock", "flag:LATE", lambda r: "LATE" in (r.get("flags") or [])),
    ("early", "Left early", "#ea580c", "door", "flag:LEFT_EARLY", lambda r: "LEFT_EARLY" in (r.get("flags") or [])),
    ("short_leave", "Short leave", "#0284c7", "cup", "perm",
     lambda r: bool({"PERMISSION", "PERMISSION_PENDING"} & set(r.get("flags") or []))),
]
COLOR = {**{b[0]: b[3] for b in BUCKETS}, **{f[0]: f[2] for f in FLAG_CARDS}}


def bucket(row: dict) -> str:
    st, flags = row.get("status"), row.get("flags") or []
    if st == "ABSENT":
        return "absent"
    if st == "NO_RECORD":
        return "no_record"
    if st == "MISSING_PUNCH":
        return "missing"
    if st == "WFH":
        return "wfh"
    if st == "ON_DUTY":
        return "od"
    if st in ("LEAVE", "HALF_DAY"):
        return "leave"
    if st in ("WEEK_OFF", "HOLIDAY", "NOT_TRACKED"):
        return "not_counted"
    return "present"                     # on time, late, left early or on short leave: all counted present


def _list_label(r: dict) -> str:
    """Status shown in the full list: late / early people are Present, with what happened next to it."""
    base = r.get("status_label") or r.get("status") or ""
    flags = r.get("flags") or []
    extra = [x for x, f in (("late", "LATE"), ("left early", "LEFT_EARLY")) if f in flags]
    return f"{base} · {' & '.join(extra)}" if extra and r.get("status") == "PRESENT" else base


def _pct(n: int, total: int) -> float | None:
    return round(100 * n / total, 1) if total else None


def exception_status(row: dict) -> tuple[str, str]:
    """(label, bucket key for the colour) of the status pill in the exceptions table."""
    st, flags = row.get("status"), row.get("flags") or []
    if st == "ABSENT":
        return "Absent", "absent"
    if st == "NO_RECORD":
        return "No attendance record", "no_record"
    if st == "MISSING_PUNCH":
        has_in, has_out = bool(row.get("in_time")), bool(row.get("out_time"))
        side = " (out)" if has_in and not has_out else " (in)" if has_out and not has_in else ""
        return f"Missing punch{side}", "missing"
    if "LATE" in flags and "LEFT_EARLY" in flags:
        return "Present · late & left early", "late"
    if "LATE" in flags:
        return "Present · late arrival", "late"
    if "LEFT_EARLY" in flags:
        return "Present · left early", "early"
    return "Present · permission pending", "short_leave"


def action_for(row: dict, pattern: str | None) -> str:
    """What the manager should do about one exception (plain words, no system jargon)."""
    st, flags = row.get("status"), row.get("flags") or []
    if "PERMISSION_PENDING" in flags:
        return "Review and approve / reject the short leave in Pocket HRMS"
    if "ON_DUTY_PENDING" in flags and st in ("ABSENT", "MISSING_PUNCH", "NO_RECORD"):
        return "Review and approve / reject the on-duty request in Pocket HRMS"
    if st == "ABSENT":
        if pattern and "absent" in pattern:
            return "Speak to the employee - absent on consecutive days"
        return "Follow up; apply leave or regularise in Pocket HRMS"
    if st == "NO_RECORD":
        return "Check with HR - no attendance record in Pocket HRMS"
    if st == "MISSING_PUNCH":
        return "Verify and regularise the missing punch"
    if "LATE" in flags and "LEFT_EARLY" in flags:
        return "Speak to them - came in late and left early"
    if "LATE" in flags:
        if pattern and "late" in pattern:
            return "Counsel and monitor - repeated late arrival"
        return "Note the late arrival; monitor"
    if "LEFT_EARLY" in flags:
        return "Check the reason; apply short leave if agreed"
    return "Review"


def action_icon(row: dict, pattern: str | None) -> str:
    st, flags = row.get("status"), row.get("flags") or []
    if "PERMISSION_PENDING" in flags or "ON_DUTY_PENDING" in flags or st == "MISSING_PUNCH":
        return "check-square"
    if st == "NO_RECORD":
        return "help"
    if "LATE" in flags and pattern and "late" in pattern:
        return "user-cog"
    return "chat"


def _metric(label: str, icon: str, now, before, pct: bool = False, up_is_good: bool | None = False, filter_: str = "") -> dict:
    """up_is_good None: neither direction is good or bad (leave, WFH, short leave) - the change is shown in grey."""
    fmt = (lambda x: f"{x:g}%") if pct else (lambda x: f"{x:g}")
    delta = None if now is None or before is None else round(now - before, 1)
    if delta is None:
        trend, text = "none", "–"
    elif delta == 0:
        trend, text = "same", "no change"
    else:
        trend = "move" if up_is_good is None else "good" if (delta > 0) == up_is_good else "bad"
        text = f"{'▲' if delta > 0 else '▼'} {abs(delta):g}" + (" pts" if pct else "")
    return {"label": label, "icon": icon, "value": "–" if now is None else fmt(now), "trend": trend, "delta": text,
            "before": None if before is None else fmt(before), "filter": filter_}


def _short_leave(rows: list[dict]) -> int:
    return sum(1 for r in rows if {"PERMISSION", "PERMISSION_PENDING"} & set(r.get("flags") or []))


def dashboard_view(rows: list[dict], summary: dict, previous_rows: list[dict] | None = None,
                   patterns: dict[str, str] | None = None) -> dict:
    """Everything the dashboard draws, computed here so the page reads well even where scripts are blocked."""
    from daily.mail import attention, counts

    patterns = patterns or {}
    rows = [r for r in rows if "status" in r]
    total = len(rows)
    tally = {k: 0 for k, *_ in BUCKETS}
    for r in rows:
        tally[bucket(r)] += 1
    flagged = {k: sum(1 for r in rows if test(r)) for k, _, _, _, _, test in FLAG_CARDS}
    inside = [f"{flagged['late']} late" if flagged["late"] else "", f"{flagged['early']} left early" if flagged["early"] else ""]
    cards = []
    for k, label, note, color, icon in BUCKETS:
        if not (tally[k] or k in ALWAYS_CARDS):
            continue
        if k == "present" and any(inside):
            note = "incl. " + ", ".join(x for x in inside if x)
        cards.append({"key": k, "label": label, "note": note, "color": color, "icon": icon, "value": tally[k],
                      "pct": _pct(tally[k], total), "filter": f"bucket:{k}"})
        if k == "absent":                                  # late / left early / short leave right after absent
            for fk, flabel, fcolor, ficon, ffilter, _ in FLAG_CARDS:
                if flagged[fk] or fk in ALWAYS_CARDS:
                    cards.append({"key": fk, "label": flabel, "note": "counted present", "color": fcolor, "icon": ficon,
                                  "value": flagged[fk], "pct": _pct(flagged[fk], total), "filter": ffilter})
    # ring chart: stroke-dasharray segments on a circle whose circumference is 100
    segments, offset = [], 0.0
    for k, label, _, color, _ in BUCKETS:
        if tally[k] and total:
            share = 100 * tally[k] / total
            segments.append({"key": k, "label": label, "color": color, "value": tally[k], "pct": _pct(tally[k], total),
                             "dash": f"{share:.3f} {100 - share:.3f}", "offset": f"{25 - offset:.3f}"})
            offset += share
    c = counts(rows) if rows else {}
    p = counts(previous_rows) if previous_rows else {}
    att_pct = c.get("attendance_pct")
    if att_pct is None:
        att_pct = summary.get("attendance_pct")
    metrics = [
        _metric("Attendance", "trend", att_pct, p.get("attendance_pct"), pct=True, up_is_good=True),
        _metric("Absent", "user-x", c.get("absent"), p.get("absent"), filter_="bucket:absent"),
        _metric("Late arrivals", "clock", c.get("late"), p.get("late"), filter_="flag:LATE"),
        _metric("Missing punch", "scan", c.get("missing_punch"), p.get("missing_punch"), filter_="bucket:missing"),
        _metric("Left early", "door", c.get("left_early"), p.get("left_early"), filter_="flag:LEFT_EARLY"),
        _metric("Short leave", "cup", _short_leave(rows) if rows else None, _short_leave(previous_rows) if p else None,
                up_is_good=None, filter_="perm"),
        _metric("On leave", "calendar", c.get("leave"), p.get("leave"), up_is_good=None, filter_="bucket:leave"),
        _metric("Work from home", "laptop", c.get("wfh"), p.get("wfh"), up_is_good=None, filter_="bucket:wfh"),
    ]
    order = {"absent": 0, "no_record": 1, "missing": 2, "late": 3, "early": 4, "short_leave": 5}
    exceptions = []
    for r in rows:
        reason = attention(r)
        if not reason and "PERMISSION_PENDING" not in (r.get("flags") or []):
            continue
        label, key = exception_status(r)
        pattern = patterns.get(str(r.get("code", "")).upper())
        details = []
        flags = r.get("flags") or []
        if r.get("status") == "ABSENT":
            details.append("No punch recorded")
        elif r.get("status") == "MISSING_PUNCH":
            details.append("Only one punch recorded")
        if "LATE" in flags and r.get("late_minutes"):
            details.append(f"Late by {mins_hm(r['late_minutes'])} hrs")
        if "LEFT_EARLY" in flags and r.get("early_minutes"):
            details.append(f"{mins_hm(r['early_minutes'])} hrs short of the required hours")
        if r.get("permission"):
            details.append(f"Permission {r['permission'].replace('Approved', 'approved').replace('Pending', 'pending')}")
        if r.get("on_duty"):
            details.append(r["on_duty"])
        if pattern:
            details.append(pattern[0].upper() + pattern[1:])
        exceptions.append({"code": r.get("code", ""), "name": r.get("name", ""), "department": r.get("department") or "",
                           "pattern": pattern, "in24": r.get("in_time") or "", "out24": r.get("out_time") or "",
                           "minutes": round(float(r["work_hours"]) * 60) if r.get("work_hours") not in (None, "") else -1,
                           "status": label, "color": COLOR[key], "in": t12(r.get("in_time")) or "–",
                           "out": t12(r.get("out_time")) or "–", "hours": hm(r.get("work_hours")) or "–",
                           "details": " · ".join(details) or "–", "action": action_for(r, pattern),
                           "action_icon": action_icon(r, pattern), "order": order.get(key, 9)})
    exceptions.sort(key=lambda x: (x["order"], x["name"]))
    pending_only = sum(1 for x in exceptions if x["order"] == order["short_leave"])
    return {"total": total, "cards": cards, "segments": segments, "attendance_pct": att_pct, "metrics": metrics,
            "has_previous": bool(p), "exceptions": exceptions,
            "need": len(exceptions) - pending_only, "to_approve": pending_only}   # same split as the email


def dashboard_html_for(company: str, report_date: date, title: str, summary: dict, highlights: list[dict], arrivals: list[dict],
                       breakdown_: dict, rows: list[dict], date_format: str, sources: str = "Pocket HRMS",
                       late_after: str | None = None, routing_columns: bool = True, *, recipient: str | None = None,
                       previous_rows: list[dict] | None = None, previous_date: date | None = None,
                       patterns: dict[str, str] | None = None, subtitle: str | None = None, company_view: bool = False) -> bytes:
    """The self-contained dashboard for any set of people. routing_columns=False (emailed dashboards) leaves out
    each person's department, HOD, team and reporting manager and greets the recipient by name."""
    keys = ("code", "name", "category", "department", "hod", "team", "manager", "permission", "on_duty", "status", "status_label",
            "in_time", "out_time", "work_hours", "late_minutes", "early_minutes", "leave_type", "flags")
    if not routing_columns:      # emailed: no hierarchy, except the HOD column of the Director's / HR's company view
        keys = tuple(k for k in keys if k not in ("department", "team", "manager") and (company_view or k != "hod"))
    summary = summary or {}
    view = dashboard_view(rows, summary, previous_rows, patterns)
    emailed = not routing_columns
    exc = {x["code"]: {k: x[k] for k in ("status", "color", "details", "action", "pattern")} for x in view["exceptions"]}
    payload = {
        "summary": summary,
        "rows": [{**{k: r.get(k, "") for k in keys}, "bucket": bucket(r), "exc": exc.get(r.get("code")),
                  "status_label": _list_label(r)} for r in rows],
        "routing_columns": routing_columns,
        "buckets": {k: {"label": label, "color": color} for k, label, _, color, _ in BUCKETS},
    }
    # Safe to embed inside <script>: no "</" or "<!--" can appear in the JSON text.
    data_json = json.dumps(payload, ensure_ascii=False).replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
    bd = breakdown_ or {"by": "Category", "rows": []}
    return _env.get_template("dashboard.html").render(
        title=title, data_json=data_json, logo=logo_data_uri(), v=view, emailed=emailed, recipient=recipient, company_view=company_view,
        heading=("Daily Company Attendance Dashboard" if company_view else "Daily Team Attendance Dashboard") if emailed
        else "Daily Attendance Dashboard",
        subtitle=subtitle or (("Company – attendance by team, exceptions & actions" if company_view
                               else "Your team – attendance, exceptions & actions") if emailed else title),
        day=report_date.strftime(date_format), long_day=f"{report_date:%a}, {report_date.day} {report_date:%b %Y}",
        previous_day=previous_date.strftime(date_format) if previous_date else None,
        highlights=[] if emailed else (highlights or []), arrivals=[] if emailed else (arrivals or []),
        breakdown=bd if len(bd.get("rows") or []) > 1 and (company_view or not emailed) else None,
        avg_in=summary.get("avg_in_time"), avg_hours=hm(summary.get("avg_work_hours")),
        sources=sources, office_opens=t12(late_after) if late_after else None, company=company,
    ).encode("utf-8")


def dashboard_html(company: str, report_date: date, scope: str, insights: dict, rows: list[dict], date_format: str,
                   previous_rows: list[dict] | None = None, previous_date: date | None = None) -> bytes:
    """In-app dashboard of one scope. previous_rows = all rows of the previous report day (compared in Key insights)."""
    data = insights["scopes"][scope]
    return dashboard_html_for(company, report_date, f"Daily Attendance - {scope_label(scope)}", data["summary"], data["highlights"],
                              data["arrivals"], breakdown(insights, scope), scoped_rows(rows, scope), date_format,
                              sources_label(insights), insights["rules"]["late_after"], subtitle=scope_label(scope),
                              previous_rows=scoped_rows(previous_rows, scope) if previous_rows else None,
                              previous_date=previous_date)
