"""Report generation, registry, approval and authorised download (PRD 11, 13.5)."""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from core.config import Settings
from core.timeutils import now_utc, to_ist
from database.models.attendance import FactAttendanceDaily, ProcessingRun
from database.models.reporting import ReportApproval, ReportRegistry
from ingestion.checksum import sha256_bytes
from reporting import report_data
from reporting.writers import to_html, to_xlsx
from security.audit import record_activity
from security.authorization import can_access_department, has_permission
from security.permissions import Perm, Principal

FORMATS = (("XLSX", "xlsx", to_xlsx), ("HTML", "html", to_html))


class ReportError(Exception):
    pass


def _write(session: Session, settings: Settings, run: ProcessingRun, report_type: str, data: dict,
           department: str | None, actor: str) -> list[ReportRegistry]:
    created = []
    for fmt, ext, writer in FORMATS:
        version = (session.scalar(select(func.max(ReportRegistry.report_version)).where(
            ReportRegistry.run_id == run.run_id, ReportRegistry.report_type == report_type,
            ReportRegistry.file_format == fmt,
            ReportRegistry.department_code.is_(None) if department is None else ReportRegistry.department_code == department)) or 0) + 1
        generated = now_utc()
        meta = data["meta"] + [("Generated", to_ist(generated).strftime(settings.app.datetime_format) + " IST"),
                               ("Report version", str(version))]
        content = writer(data, meta)
        folder = settings.storage.area("reports") / run.reporting_date.isoformat() / run.run_ref
        folder.mkdir(parents=True, exist_ok=True)
        name = f"{report_type}{'_' + department if department else ''}_v{version}.{ext}"
        path = folder / name
        path.write_bytes(content)
        row = ReportRegistry(run_id=run.run_id, report_type=report_type, department_code=department, file_format=fmt,
                             report_version=version, file_path=str(path), sha256=sha256_bytes(content),
                             provisional=data["provisional"], status="GENERATED", generated_by=actor, generated_at=generated)
        session.add(row)
        created.append(row)
    session.flush()
    return created


def generate_for_run(session: Session, settings: Settings, run_id: int, actor: str) -> list[ReportRegistry]:
    run = session.get(ProcessingRun, run_id)
    if run is None:
        raise ReportError("Run not found.")
    created: list[ReportRegistry] = []
    departments = sorted({d for (d,) in session.execute(select(FactAttendanceDaily.department_code).where(
        FactAttendanceDaily.run_id == run_id).distinct()) if d})
    for dept in departments:
        created += _write(session, settings, run, "HOD", report_data.hod(session, settings, run, dept), dept, actor)
    created += _write(session, settings, run, "DIRECTORS", report_data.directors(session, settings, run), None, actor)
    created += _write(session, settings, run, "HR_ADMIN", report_data.hr_admin(session, settings, run), None, actor)
    return created


def can_view(principal: Principal, report: ReportRegistry) -> bool:
    """Server-side report access (PRD 3.3, 11.2, 23.3)."""
    if report.report_type == "HOD":
        return has_permission(principal, Perm.REPORT_VIEW_HOD) and can_access_department(principal, report.department_code or "")
    if report.report_type == "DIRECTORS":
        return has_permission(principal, Perm.REPORT_VIEW_DIRECTORS)
    return has_permission(principal, Perm.REPORT_GENERATE) or has_permission(principal, Perm.SYSTEM_MONITOR)


def visible_reports(session: Session, principal: Principal, run_id: int | None = None) -> list[ReportRegistry]:
    q = select(ReportRegistry).order_by(ReportRegistry.report_id.desc()).limit(500)
    if run_id is not None:
        q = q.where(ReportRegistry.run_id == run_id)
    return [r for r in session.scalars(q) if can_view(principal, r)]


def open_report(session: Session, settings: Settings, principal: Principal, report_id: int) -> tuple[ReportRegistry, bytes]:
    report = session.get(ReportRegistry, report_id)
    if report is None or not can_view(principal, report):
        raise LookupError("report not found")
    path = Path(report.file_path).resolve()
    if not path.is_relative_to(settings.storage.area("reports").resolve()):
        raise LookupError("report not found")
    content = path.read_bytes()
    if sha256_bytes(content) != report.sha256:
        raise ReportError("The stored report file does not match its recorded checksum.")
    record_activity(session, "REPORT_DOWNLOAD", "SUCCESS", user_id=principal.user_id or None, username=principal.username,
                    detail={"report_id": report_id, "type": report.report_type, "department": report.department_code})
    return report, content


def decide(session: Session, report_id: int, principal: Principal, decision: str, comment: str | None) -> ReportRegistry:
    report = session.get(ReportRegistry, report_id)
    if report is None:
        raise LookupError("report not found")
    if decision not in ("APPROVED", "REJECTED"):
        raise ReportError("Decision must be APPROVED or REJECTED.")
    if report.status not in ("GENERATED",):
        raise ReportError(f"Report is already {report.status}.")
    report.status = decision
    session.add(ReportApproval(report_id=report_id, decision=decision, actor=principal.username, comment=comment))
    record_activity(session, "REPORT_DECISION", decision, username=principal.username, detail={"report_id": report_id})
    session.flush()
    return report
