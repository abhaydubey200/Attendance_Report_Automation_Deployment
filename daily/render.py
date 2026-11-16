"""Renders the interactive HTML dashboard and the email (HTML + plain text)."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from daily.analysis import HOD_PREFIX, in_scope, t12
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
    return "Pocket HRMS (attendance + permissions)" if src.get("permission_file") else "Pocket HRMS"


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


def dashboard_html_for(company: str, report_date: date, title: str, summary: dict, highlights: list[dict], arrivals: list[dict],
                       breakdown_: dict, rows: list[dict], date_format: str, sources: str = "Pocket HRMS",
                       late_after: str | None = None, routing_columns: bool = True) -> bytes:
    """The self-contained interactive dashboard for any set of people. routing_columns=False (emailed dashboards)
    leaves out each person's HOD, team and reporting manager."""
    keys = ("code", "name", "category", "department", "hod", "team", "manager", "permission", "status", "status_label",
            "in_time", "out_time", "work_hours", "late_minutes", "early_minutes", "leave_type", "flags")
    if not routing_columns:
        keys = tuple(k for k in keys if k not in ("department", "hod", "team", "manager"))
    payload = {
        "title": title,
        "subtitle": f"{report_date.strftime(date_format)} · source: {sources}",
        "summary": summary, "highlights": highlights, "arrivals": arrivals, "breakdown": breakdown_,
        "rows": [{k: r.get(k, "") for k in keys} for r in rows],
        "routing_columns": routing_columns,
        "footer": f"Generated automatically from {sources} for {report_date.strftime(date_format)}."
                  + (f" Office opens {t12(late_after)}; late rules as in the attendance settings." if late_after else ""),
    }
    # Safe to embed inside <script>: no "</" or "<!--" can appear in the JSON text.
    data_json = json.dumps(payload, ensure_ascii=False).replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
    return _env.get_template("dashboard.html").render(title=title, data_json=data_json, logo=logo_data_uri()).encode("utf-8")


def dashboard_html(company: str, report_date: date, scope: str, insights: dict, rows: list[dict], date_format: str) -> bytes:
    data = insights["scopes"][scope]
    return dashboard_html_for(company, report_date, f"Daily Attendance - {scope_label(scope)}", data["summary"], data["highlights"],
                              data["arrivals"], breakdown(insights, scope), scoped_rows(rows, scope), date_format,
                              sources_label(insights), insights["rules"]["late_after"])
