"""Attendance over a date range: one employee's day-by-day report, and a filtered report for many
employees (by HOD, department, team, reporting manager, category, status, source), with Excel export."""

from __future__ import annotations

import io
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date, timedelta

import xlsxwriter
from sqlalchemy import select
from sqlalchemy.orm import Session

from core.config import Rules
from daily import employees
from daily.analysis import STATUS_LABEL, UNCOUNTED
from database.models.daily import DayUpload, EmployeeDay

MAX_DAYS = 186


@dataclass
class Filters:
    start: date
    end: date
    hod: str = ""
    department: str = ""
    team: str = ""
    manager: str = ""
    category: str = ""
    status: str = ""          # a status code, LATE, or "" for all
    source: str = ""          # HRMS | BIZOM | HRMS+BIZOM
    q: str = ""

    def check(self) -> None:
        if self.end < self.start:
            raise ValueError("'To' date is before 'From' date.")
        if (self.end - self.start).days > MAX_DAYS:
            raise ValueError(f"Choose at most {MAX_DAYS} days.")

    def as_text(self) -> str:
        parts = [f"{k}: {v}" for k, v in (("HOD", self.hod), ("Department", self.department), ("Team", self.team),
                                          ("Reporting manager", self.manager), ("Category", self.category),
                                          ("Status", STATUS_LABEL.get(self.status, self.status.title())), ("Source", self.source),
                                          ("Search", self.q)) if v]
        return "; ".join(parts) or "none"


def default_range(session: Session) -> tuple[date, date]:
    last = session.scalar(select(DayUpload.report_date).where(DayUpload.is_current.is_(True)).order_by(DayUpload.report_date.desc()))
    end = last or date.today()
    return end - timedelta(days=29), end


def _rows(session: Session, start: date, end: date, code: str | None = None) -> list[tuple[date, EmployeeDay]]:
    stmt = (select(DayUpload.report_date, EmployeeDay).join(EmployeeDay, EmployeeDay.upload_id == DayUpload.upload_id)
            .where(DayUpload.is_current.is_(True), DayUpload.report_date >= start, DayUpload.report_date <= end))
    if code:
        stmt = stmt.where(EmployeeDay.employee_code.in_({code, code.upper(), code.lower()}))
    return [(d, e) for d, e in session.execute(stmt.order_by(DayUpload.report_date, EmployeeDay.employee_code)).all()]


def day_dict(d: date, e: EmployeeDay) -> dict:
    return {"date": d.isoformat(), "code": e.employee_code, "name": e.employee_name or "", "category": e.category,
            "department": e.department or "", "hod": e.hod_name or "", "team": e.team or "", "manager": e.reporting_manager or "",
            "status": e.status, "status_label": STATUS_LABEL.get(e.status, e.status), "in_time": e.in_time, "out_time": e.out_time,
            "work_hours": round(e.work_minutes / 60, 2) if e.work_minutes is not None else None, "late_minutes": e.late_minutes,
            "early_minutes": e.early_minutes, "leave_type": e.leave_type, "source": e.source or "HRMS",
            "bizom_status": e.bizom_status or "", "flags": (e.flags or "").split(",") if e.flags else []}


def _tally(days: list[dict], rules: Rules) -> dict:
    c = Counter(x["status"] for x in days)
    tracked = len(days) - sum(c[s] for s in UNCOUNTED)
    present_eq = (c["PRESENT"] + c["ON_DUTY"] + c["WFH"] + (c["MISSING_PUNCH"] if rules.single_punch_counts_present else 0)
                  + 0.5 * c["HALF_DAY"])
    late = [x for x in days if "LATE" in x["flags"]]
    ins = [int(x["in_time"][:2]) * 60 + int(x["in_time"][3:5]) for x in days if x["in_time"] and x["status"] in ("PRESENT", "MISSING_PUNCH")]
    hours = [x["work_hours"] for x in days if x["work_hours"] is not None]
    avg_in = round(sum(ins) / len(ins)) if ins else None
    return {"days": len(days), "tracked": tracked, "present": c["PRESENT"] + c["ON_DUTY"] + c["WFH"], "wfh": c["WFH"], "missing_punch": c["MISSING_PUNCH"],
            "half_day": c["HALF_DAY"], "leave": c["LEAVE"], "absent": c["ABSENT"], "week_off": c["WEEK_OFF"],
            "not_tracked": c["NOT_TRACKED"], "late": len(late), "left_early": sum(1 for x in days if "LEFT_EARLY" in x["flags"]),
            "attendance_pct": round(100 * present_eq / tracked, 1) if tracked else None,
            "avg_in_time": f"{avg_in // 60:02d}:{avg_in % 60:02d}" if avg_in is not None else None,
            "avg_work_hours": round(sum(hours) / len(hours), 2) if hours else None}


# ---------------------------------------------------------------------------- one employee
def employee_report(session: Session, code: str, start: date, end: date, rules: Rules) -> dict:
    code = employees.norm_code(code)
    days = [day_dict(d, e) for d, e in _rows(session, start, end, code)]
    try:
        master = employees.to_dict(employees.get(session, code))
    except LookupError:
        master = None
    if master is None and not days:
        raise LookupError(f"No employee or attendance found for {code}.")
    latest = days[-1] if days else {}
    profile = master or {"code": code, "name": latest.get("name", ""), "department": latest.get("department", ""),
                         "hod_name": latest.get("hod", ""), "team": latest.get("team", ""),
                         "reporting_manager": latest.get("manager", ""), "status": None}
    return {"employee": profile, "in_master": master is not None, "from": start.isoformat(), "to": end.isoformat(),
            "summary": _tally(days, rules), "days": days}


# ---------------------------------------------------------------------------- many employees
def _match(x: dict, f: Filters, skip: str = "") -> bool:
    q = f.q.strip().lower()
    return ((skip == "hod" or not f.hod or x["hod"] == f.hod)
            and (skip == "department" or not f.department or x["department"] == f.department)
            and (skip == "team" or not f.team or x["team"] == f.team)
            and (skip == "manager" or not f.manager or x["manager"] == f.manager)
            and (skip == "category" or not f.category or x["category"] == f.category)
            and (skip == "source" or not f.source or x["source"] == f.source)
            and (not q or any(q in (x[k] or "").lower() for k in ("code", "name", "team", "manager"))))


def attendance_report(session: Session, f: Filters, rules: Rules, with_days: bool = False) -> dict:
    """Per-employee totals for the range. The status filter keeps employees who had that status at least once
    (and, in the daily list, only those days)."""
    f.check()
    all_days = [day_dict(d, e) for d, e in _rows(session, f.start, f.end)]
    options = {k: sorted({x[k] for x in all_days if _match(x, f, k) and x[k]}) for k in
               ("hod", "department", "team", "manager", "category", "source")}
    days = [x for x in all_days if _match(x, f)]
    per: dict[str, list[dict]] = defaultdict(list)
    for x in days:
        per[x["code"]].append(x)

    def has_status(items: list[dict]) -> bool:
        if not f.status:
            return True
        if f.status == "LATE":
            return any("LATE" in x["flags"] for x in items)
        return any(x["status"] == f.status for x in items)

    people = []
    for code, items in per.items():
        if not has_status(items):
            continue
        last = items[-1]
        people.append({"code": code, "name": last["name"], "category": last["category"], "department": last["department"],
                       "hod": last["hod"], "team": last["team"], "manager": last["manager"], **_tally(items, rules)})
    people.sort(key=lambda p: (p["department"], p["name"]))
    kept = {p["code"] for p in people}
    kept_days = [x for x in days if x["code"] in kept]
    if f.status:
        kept_days = [x for x in kept_days if ("LATE" in x["flags"] if f.status == "LATE" else x["status"] == f.status)]
    dates = sorted({x["date"] for x in all_days})
    out = {"from": f.start.isoformat(), "to": f.end.isoformat(), "dates": dates, "options": options,
           "totals": _tally([x for x in days if x["code"] in kept], rules) | {"employees": len(people)}, "employees": people}
    if with_days:
        out["days"] = kept_days
    return out


def attendance_excel(company: str, report: dict, f: Filters, date_format: str) -> bytes:
    buf = io.BytesIO()
    wb = xlsxwriter.Workbook(buf, {"in_memory": True, "strings_to_formulas": False, "strings_to_urls": False})
    title = wb.add_format({"bold": True, "font_size": 15, "font_color": "#835415"})
    sub = wb.add_format({"italic": True, "font_color": "#6E6152"})
    head = wb.add_format({"bold": True, "font_color": "#FFFFFF", "bg_color": "#835415", "text_wrap": True, "valign": "vcenter"})
    cell = wb.add_format({"border": 1, "border_color": "#ECDFC9"})
    fmt_d = lambda iso: date.fromisoformat(iso).strftime(date_format)  # noqa: E731

    ws = wb.add_worksheet("Summary")
    ws.write(0, 0, f"{company} - Attendance report", title)
    ws.write(1, 0, f"{fmt_d(report['from'])} to {fmt_d(report['to'])} · {len(report['dates'])} uploaded day(s) · "
                   f"{report['totals']['employees']} employees · filters: {f.as_text()}", sub)
    cols = [("Code", "code", 12), ("Name", "name", 26), ("Department", "department", 18), ("HOD", "hod", 18), ("Team", "team", 14),
            ("Reporting manager", "manager", 20), ("Category", "category", 12), ("Days", "days", 7), ("Present", "present", 9),
            ("Missing punch", "missing_punch", 9), ("Half day", "half_day", 8), ("Leave", "leave", 8), ("Absent", "absent", 8),
            ("Week off", "week_off", 8), ("Not tracked", "not_tracked", 9), ("Late", "late", 7), ("Left early", "left_early", 8),
            ("Attendance %", "attendance_pct", 11), ("Avg arrival", "avg_in_time", 10), ("Avg hours", "avg_work_hours", 9)]
    for j, (h, _, w) in enumerate(cols):
        ws.write(3, j, h, head)
        ws.set_column(j, j, w)
    for i, p in enumerate(report["employees"], start=4):
        for j, (_, k, _) in enumerate(cols):
            v = p.get(k)
            ws.write(i, j, "" if v is None else v, cell)
    ws.freeze_panes(4, 2)
    if report["employees"]:
        ws.autofilter(3, 0, 3 + len(report["employees"]), len(cols) - 1)

    ws2 = wb.add_worksheet("Daily")
    dcols = [("Date", "date", 12), ("Code", "code", 12), ("Name", "name", 26), ("Department", "department", 18), ("HOD", "hod", 18),
             ("Team", "team", 14), ("Status", "status_label", 13), ("In", "in_time", 7), ("Out", "out_time", 7),
             ("Hours", "work_hours", 7), ("Late (min)", "late_minutes", 9), ("Leave type", "leave_type", 9),
             ("Source", "source", 12), ("Bizom", "bizom_status", 7)]
    for j, (h, _, w) in enumerate(dcols):
        ws2.write(0, j, h, head)
        ws2.set_column(j, j, w)
    for i, x in enumerate(report.get("days", []), start=1):
        for j, (_, k, _) in enumerate(dcols):
            v = fmt_d(x[k]) if k == "date" else x.get(k)
            ws2.write(i, j, "" if v is None or v == 0 and k == "late_minutes" else v, cell)
    ws2.freeze_panes(1, 3)
    if report.get("days"):
        ws2.autofilter(0, 0, len(report["days"]), len(dcols) - 1)
    wb.close()
    return buf.getvalue()


def employee_excel(company: str, report: dict, date_format: str) -> bytes:
    emp = report["employee"]
    f = Filters(start=date.fromisoformat(report["from"]), end=date.fromisoformat(report["to"]), q=emp["code"])
    summary = {"code": emp["code"], "name": emp["name"], "department": emp.get("department", ""), "hod": emp.get("hod_name", ""),
               "team": emp.get("team", ""), "manager": emp.get("reporting_manager", ""), "category": "", **report["summary"]}
    data = {"from": report["from"], "to": report["to"], "dates": sorted({d["date"] for d in report["days"]}),
            "totals": {"employees": 1}, "employees": [summary], "days": report["days"]}
    return attendance_excel(company, data, f, date_format)
