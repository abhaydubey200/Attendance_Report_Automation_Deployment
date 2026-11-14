"""Collects the numbers a report shows, straight from the run's stored results.
Reports never recalculate attendance; they present what the engine recorded."""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from core.config import Settings, load_attendance_rules
from core.timeutils import to_ist
from database.models.attendance import AttendanceException, AttendanceReconciliation, FactAttendanceDaily, ProcessingRun
from database.models.audit import EmailDeliveryLog, ProcessingLog
from database.models.hr import DimDepartment, DimEmployee
from database.models.reporting import AISummary, ReportRegistry
from database.models.staging import UploadRegistry
from data_engine import kpi_calculator

STATUS_ORDER = ["PRESENT", "ABSENT", "APPROVED_LEAVE", "WORK_FROM_HOME", "HALF_DAY", "MISSING_PUNCH",
                "PENDING_APPROVAL", "WEEKLY_OFF", "HOLIDAY", "UNRESOLVED"]


def _fmt_dt(settings: Settings, value) -> str:
    return to_ist(value).strftime(settings.app.datetime_format) + " IST" if value else ""


def _pct(v) -> str:
    return "Pending HR approval" if v is None else f"{v:.2f}%"


def base(session: Session, settings: Settings, run: ProcessingRun) -> dict:
    rules = load_attendance_rules(settings.config_dir)
    uploads = list(session.scalars(select(UploadRegistry).where(
        UploadRegistry.upload_id.in_([int(k) for k in json.loads(run.inputs).get("uploads", {})]))))
    freshness = max((u.uploaded_at for u in uploads), default=None)
    return {
        "run": run, "rules": rules,
        "provisional": not run.rules_approved,
        "meta": [
            ("Reporting period", run.reporting_date.strftime(settings.app.date_format)),
            ("Processing run", run.run_ref),
            ("Data freshness (latest upload)", _fmt_dt(settings, freshness) or "No uploads"),
            ("Rule version", f"{run.rule_version} ({'approved' if run.rules_approved else 'NOT approved - provisional'})"),
        ],
        "uploads": uploads,
    }


def _facts(session: Session, run_id: int, department: str | None = None):
    q = (select(FactAttendanceDaily, DimEmployee).join(DimEmployee, DimEmployee.employee_key == FactAttendanceDaily.employee_key)
         .where(FactAttendanceDaily.run_id == run_id).order_by(DimEmployee.employee_code))
    if department is not None:
        q = q.where(FactAttendanceDaily.department_code == department)
    return list(session.execute(q).all())


def _summary_rows(summary: dict) -> list[tuple[str, object]]:
    c = summary["counts"]
    rows = [("Eligible employees", summary["eligible_employees"])]
    if summary.get("active_employees") is not None:
        rows.insert(0, ("Active employees", summary["active_employees"]))
    rows += [("Present", c["PRESENT"]), ("Absent", c["ABSENT"]), ("Approved leave", c["APPROVED_LEAVE"]),
             ("WFH", c["WORK_FROM_HOME"]), ("Half day", c["HALF_DAY"]), ("Missing punch", c["MISSING_PUNCH"]),
             ("Pending approval", c["PENDING_APPROVAL"]), ("Unresolved", c["UNRESOLVED"]),
             ("Weekly off", c["WEEKLY_OFF"]), ("Holiday", c["HOLIDAY"]),
             ("Attendance %", _pct(summary["attendance_pct"])), ("Absenteeism %", _pct(summary["absenteeism_pct"]))]
    return rows


def _detail(settings: Settings, rows, statuses: set[str] | None = None) -> list[list]:
    out = []
    for fact, emp in rows:
        if statuses and fact.final_status not in statuses:
            continue
        out.append([emp.employee_code, emp.employee_name or "", fact.department_code or "", fact.final_status,
                    to_ist(fact.first_in).strftime("%H:%M") if fact.first_in else "",
                    to_ist(fact.last_out).strftime("%H:%M") if fact.last_out else "",
                    fact.leave_status or "", fact.reason or ""])
    return out


DETAIL_HEADER = ["Employee code", "Name", "Department", "Status", "First in (IST)", "Last out (IST)", "Leave", "Reason"]


def _recon_rows(session: Session, run_id: int, department: str | None, employee_level: bool) -> list[list]:
    q = select(AttendanceReconciliation).where(AttendanceReconciliation.run_id == run_id,
                                               AttendanceReconciliation.category != "MATCHED")
    rows = list(session.scalars(q))
    if department is not None:
        keys = {f.employee_key for f, _ in _facts(session, run_id, department)}
        rows = [r for r in rows if r.employee_key in keys]
    if not employee_level:
        return [[cat, n] for cat, n in sorted(Counter(r.category for r in rows).items())]
    return [[r.category, r.source_employee_id or "", r.bizom_value or "", r.hrms_value or "", r.detail or ""] for r in rows]


def _quality(b: dict) -> list[list]:
    return [[u.dataset_id, u.original_filename, u.validation_status, u.total_rows, u.valid_rows, u.invalid_rows,
             u.duplicate_rows, u.warning_count] for u in b["uploads"]]


QUALITY_HEADER = ["Dataset", "File", "Validation", "Rows", "Valid", "Invalid", "Duplicates", "Warnings"]


def hod(session: Session, settings: Settings, run: ProcessingRun, department: str) -> dict:
    b = base(session, settings, run)
    rows = _facts(session, run.run_id, department)
    summary = kpi_calculator.summarize([f.final_status for f, _ in rows], b["rules"])
    dept = session.get(DimDepartment, department)
    title = f"HOD Attendance MIS - {dept.department_name if dept else department}"
    leave = [[e.employee_code, e.employee_name or "", f.final_status, f.leave_status or ""] for f, e in rows
             if f.leave_status or f.final_status in ("APPROVED_LEAVE", "HALF_DAY", "PENDING_APPROVAL")]
    return {**b, "title": title, "department": department, "sheets": [
        ("Executive Summary", ["Measure", "Value"], [[k, v] for k, v in [("Department", department)] + _summary_rows(summary)]),
        ("Attendance Details", DETAIL_HEADER, _detail(settings, rows)),
        ("Absent Employees", DETAIL_HEADER, _detail(settings, rows, {"ABSENT"})),
        ("Leave Details", ["Employee code", "Name", "Status", "Leave approval"], leave),
        ("Missing Punch", DETAIL_HEADER, _detail(settings, rows, {"MISSING_PUNCH"})),
        ("Reconciliation", ["Category", "Employee / source id", "Bizom", "Pocket HRMS", "Detail"],
         _recon_rows(session, run.run_id, department, employee_level=True)),
        ("Data Quality", QUALITY_HEADER, _quality(b)),
    ]}


def directors(session: Session, settings: Settings, run: ProcessingRun) -> dict:
    """Organisation level only: no employee-level rows (PRD 11.3)."""
    b = base(session, settings, run)
    rows = _facts(session, run.run_id)
    stats = json.loads(run.stats or "{}")
    summary = stats.get("kpis") or kpi_calculator.summarize([f.final_status for f, _ in rows], b["rules"])
    names = {d.department_code: d.department_name for d in session.scalars(select(DimDepartment))}
    by_dept, by_loc = defaultdict(list), defaultdict(list)
    for f, _ in rows:
        by_dept[f.department_code or "UNASSIGNED"].append(f.final_status)
        by_loc[f.location_code or "UNASSIGNED"].append(f.final_status)

    def group_rows(groups, label):
        out = []
        for key, statuses in sorted(groups.items()):
            s = kpi_calculator.summarize(statuses, b["rules"])
            c = s["counts"]
            out.append([label(key), s["eligible_employees"], c["PRESENT"], c["ABSENT"], c["APPROVED_LEAVE"],
                        c["WORK_FROM_HOME"], c["HALF_DAY"], c["MISSING_PUNCH"], c["UNRESOLVED"],
                        _pct(s["attendance_pct"]), _pct(s["absenteeism_pct"])])
        return out

    group_header = ["", "Eligible", "Present", "Absent", "Leave", "WFH", "Half day", "Missing punch", "Unresolved",
                    "Attendance %", "Absenteeism %"]
    trend = []
    for r in session.scalars(select(ProcessingRun).where(ProcessingRun.is_current.is_(True),
                                                         ProcessingRun.reporting_date > run.reporting_date - timedelta(days=31),
                                                         ProcessingRun.reporting_date <= run.reporting_date)
                             .order_by(ProcessingRun.reporting_date)):
        k = json.loads(r.stats or "{}").get("kpis")
        if k:
            c = k["counts"]
            trend.append([r.reporting_date.strftime(settings.app.date_format), k["eligible_employees"], c["PRESENT"],
                          c["ABSENT"], c["APPROVED_LEAVE"], _pct(k["attendance_pct"])])
    critical = Counter((e.category, e.severity) for e in session.scalars(select(AttendanceException).where(
        AttendanceException.run_id == run.run_id, AttendanceException.severity.in_(["HIGH", "CRITICAL"]))))
    ai = session.scalar(select(AISummary).where(AISummary.run_id == run.run_id, AISummary.scope == "ORG")
                        .order_by(AISummary.id.desc()))
    ai_rows = [["AI commentary", ai.summary]] if ai and ai.status == "GENERATED" else \
        [["AI commentary", "Unavailable for this run (AI is optional and does not affect any figure)."]]
    return {**b, "title": "Directors Consolidated Attendance MIS", "department": None, "sheets": [
        ("Executive Dashboard", ["Measure", "Value"], [[k, v] for k, v in _summary_rows(summary)]
         + [["Critical exceptions", sum(critical.values())]]),
        ("Department Summary", ["Department"] + group_header[1:], group_rows(by_dept, lambda k: f"{k} - {names.get(k, '')}".strip(" -"))),
        ("Location Summary", ["Location"] + group_header[1:], group_rows(by_loc, str)),
        ("Attendance Trends", ["Date", "Eligible", "Present", "Absent", "Leave", "Attendance %"], trend),
        ("Critical Exceptions", ["Category", "Severity", "Count"], [[c, s, n] for (c, s), n in sorted(critical.items())]),
        ("Reconciliation", ["Category", "Count"], _recon_rows(session, run.run_id, None, employee_level=False)),
        ("Data Quality", QUALITY_HEADER, _quality(b)),
        ("AI Insights", ["Item", "Text"], ai_rows),
    ]}


def hr_admin(session: Session, settings: Settings, run: ProcessingRun) -> dict:
    b = base(session, settings, run)
    stats = json.loads(run.stats or "{}")
    logs = list(session.scalars(select(ProcessingLog).where(ProcessingLog.run_id == run.run_id).order_by(ProcessingLog.id)))
    reports = list(session.scalars(select(ReportRegistry).where(ReportRegistry.run_id == run.run_id)))
    emails = list(session.scalars(select(EmailDeliveryLog).where(EmailDeliveryLog.report_id.in_([r.report_id for r in reports])))) if reports else []
    recon = stats.get("reconciliation", {})
    overview = [
        ["Processing run", run.run_ref], ["Reporting date", run.reporting_date.strftime(settings.app.date_format)],
        ["State", run.state], ["Started by", run.started_by], ["Started", _fmt_dt(settings, run.started_at)],
        ["Processing duration (ms)", sum(l.duration_ms or 0 for l in logs)],
        ["Uploaded datasets", len(b["uploads"])], ["Missing daily datasets", ", ".join(stats.get("missing_datasets", [])) or "None"],
        ["Total source records", sum(u.total_rows for u in b["uploads"])],
        ["Valid records", sum(u.valid_rows for u in b["uploads"])], ["Invalid records", sum(u.invalid_rows for u in b["uploads"])],
        ["Mapping failures", recon.get("counts", {}).get("EMPLOYEE_MAPPING_MISSING", 0)],
        ["Reconciliation exceptions", recon.get("exceptions", 0)],
        ["Reconciliation rate", _pct(recon.get("reconciliation_rate")) if recon.get("reconciliation_rate") is not None else "n/a"],
        ["Reports generated", len(reports)], ["AI status", run.ai_status or "n/a"],
        ["Email status", ", ".join(sorted({e.status for e in emails})) or "Not distributed"],
        ["Failure message", run.error or "None"],
    ]
    return {**b, "title": "HR/Admin Operational Report", "department": None, "sheets": [
        ("Run Overview", ["Item", "Value"], overview),
        ("Processing Stages", ["Stage", "Outcome", "Duration (ms)", "Records", "Message"],
         [[l.stage, l.outcome, l.duration_ms or "", l.record_count if l.record_count is not None else "", l.message or ""] for l in logs]),
        ("Uploads", QUALITY_HEADER, _quality(b)),
        ("Reconciliation", ["Category", "Count"], [[k, v] for k, v in sorted(recon.get("counts", {}).items())]),
    ]}
