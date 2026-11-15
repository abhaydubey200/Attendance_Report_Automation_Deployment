"""Renders the interactive HTML dashboard and the email (HTML + plain text)."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from daily.analysis import HOD_PREFIX, in_scope
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
    names = [n for n, on in (("Pocket HRMS", src.get("hrms", True)), ("Bizom", src.get("bizom_file"))) if on]
    return " + ".join(names) or "Pocket HRMS"


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


def dashboard_html(company: str, report_date: date, scope: str, insights: dict, rows: list[dict], date_format: str) -> bytes:
    scoped = scoped_rows(rows, scope)
    data = insights["scopes"][scope]
    payload = {
        "title": f"Daily Attendance - {scope_label(scope)}",
        "subtitle": f"{report_date.strftime(date_format)} · {company} · source: {sources_label(insights)}",
        "summary": data["summary"], "highlights": data["highlights"], "arrivals": data["arrivals"],
        "breakdown": breakdown(insights, scope),
        "rows": [{k: r.get(k, "") for k in ("code", "name", "category", "department", "hod", "team", "manager", "source", "bizom_status", "status", "status_label", "in_time", "out_time", "work_hours",
                                    "late_minutes", "early_minutes", "leave_type", "flags")} for r in scoped],
        "footer": f"Generated automatically from {sources_label(insights)} for {report_date.strftime(date_format)}. "
                  f"Late = first punch after {insights['rules']['late_after']}.",
    }
    # Safe to embed inside <script>: no "</" or "<!--" can appear in the JSON text.
    data_json = json.dumps(payload, ensure_ascii=False).replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
    return _env.get_template("dashboard.html").render(title=payload["title"], data_json=data_json).encode("utf-8")


def email_parts(company: str, report_date: date, scope: str, insights: dict, date_format: str, subject_prefix: str,
                greeting_names: list[str], app_url: str | None) -> tuple[str, str, str]:
    """(subject, html, text) for one scope."""
    data = insights["scopes"][scope]
    s, c = data["summary"], data["summary"]["counts"]
    date_label = report_date.strftime(date_format)
    pct = "–" if s["attendance_pct"] is None else f"{s['attendance_pct']}%"
    subject = f"{subject_prefix} | {scope_label(scope)} | {date_label} | Attendance {pct}"
    kpis = [("Attendance", pct, "#835415"), ("Present", c["PRESENT"], "#2e7d4f"), ("Absent", c["ABSENT"], "#a52a1a"),
            ("Late", s["late"], "#c88a00"), ("Leave", c["LEAVE"] + c["HALF_DAY"], "#9f7b49")]
    bd = breakdown(insights, scope)
    cats = [{"name": x["name"], "hod": x.get("hod") or "", "employees": x["employees"],
             "attendance": "–" if x["attendance_pct"] is None else f"{x['attendance_pct']}%",
             "absent": x["absent"], "late": x["late"]} for x in bd["rows"]]
    greeting = f"Dear {greeting_names[0]}" if len(greeting_names) == 1 else "Dear Team"
    stem = file_stem(report_date, scope)
    html = _env.get_template("email.html").render(
        subject=subject, scope_label=scope_label(scope), date_label=date_label, company=company, greeting=greeting,
        kpis=kpis, highlights=data["highlights"], kind_colors=KIND_COLORS, categories=cats, breakdown_by=bd["by"],
        show_hod=any(x["hod"] for x in cats),
        sources=sources_label(insights), excel_name=f"{stem}.xlsx", dashboard_name=f"{stem}_dashboard.html", app_url=app_url)
    lines = [f"{greeting},", "", f"Attendance summary for {date_label} - {scope_label(scope)}", "",
             "  ".join(f"{label}: {value}" for label, value, _ in kpis), "", "Highlights:"]
    lines += [f"- {h['text']}" for h in data["highlights"]]
    if cats:
        lines += ["", f"By {bd['by'].lower()}:"] + [f"- {x['name']}: {x['attendance']} attendance, {x['absent']} absent, {x['late']} late" for x in cats]
    lines += ["", f"Attached: {stem}.xlsx and {stem}_dashboard.html (open in a browser).",
              "", f"This is an automated email from the APIS Daily Attendance tool (source: {sources_label(insights)})."]
    return subject, html, "\n".join(lines)
