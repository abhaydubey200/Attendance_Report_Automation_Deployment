"""Upload one day -> analyse -> store -> (auto) email each category manager and HR/Directors."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from core.config import Rules, Settings
from daily import analysis
from daily.analysis import FileError
from daily.excel_report import build_excel
from daily.mailer import Attachment, MailError, build_message, send
from daily.render import dashboard_html, email_parts, file_stem, scope_label
from daily.settings_store import ALL, get_email_settings, get_rules, recipients_by_scope
from database.models.daily import DayUpload, EmailLog, EmployeeDay
from ingestion.checksum import sha256_bytes
from ingestion.file_inspector import inspect_file, safe_filename
from ingestion.file_reader import ReadError, read_raw
from ingestion.reshapers import reshape_attendance_summary
from security.audit import record_activity

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


class AlreadyUploaded(Exception):
    def __init__(self, report_date: date, upload_id: int) -> None:
        super().__init__(f"{report_date:%d-%b-%Y} is already uploaded. Upload again with 'Replace' to use this file instead.")
        self.report_date, self.upload_id = report_date, upload_id


@dataclass
class EmailOutcome:
    scope: str
    recipients: list[str]
    status: str               # SENT | SAVED | FAILED | NO_RECIPIENTS
    detail: str | None = None

    def as_dict(self) -> dict:
        return {"scope": self.scope, "scope_label": scope_label(self.scope), "recipients": self.recipients,
                "status": self.status, "detail": self.detail}


# ---------------------------------------------------------------------------- reading + analysis
def read_file(settings: Settings, filename: str, data: bytes) -> list[dict]:
    check = inspect_file(filename, data, tuple(settings.uploads.allowed_extensions), settings.uploads.max_file_size_mb * 1024 * 1024)
    if not check.ok:
        raise FileError(" ".join(check.errors))
    try:
        raw_rows, sheets = read_raw(data, check.file_type)
        return reshape_attendance_summary(raw_rows, 1, sheets).rows
    except ReadError as exc:
        raise FileError(f"{exc} Is this the Pocket HRMS 'Attendance Summary' export?") from exc


def current_upload(session: Session, report_date: date) -> DayUpload | None:
    return session.scalar(select(DayUpload).where(DayUpload.report_date == report_date, DayUpload.is_current.is_(True)))


def previous_insights(session: Session, report_date: date) -> dict | None:
    prev = session.scalar(select(DayUpload).where(DayUpload.report_date < report_date, DayUpload.is_current.is_(True))
                          .order_by(DayUpload.report_date.desc()))
    return json.loads(prev.insights) if prev else None


def _analyse(session: Session, rows: list[dict], rules: Rules):
    report_date, results, excluded = analysis.classify(rows, rules)
    insights = analysis.build_insights(report_date, results, rules, excluded, previous_insights(session, report_date))
    return report_date, results, insights


def _store_rows(session: Session, upload_id: int, results) -> None:
    for r in results:
        session.add(EmployeeDay(upload_id=upload_id, employee_code=r.code, employee_name=r.name, category=r.category,
                                shift_name=r.shift, in_time=r.in_time, out_time=r.out_time, punches=r.punches,
                                work_minutes=r.work_minutes, leave_type=r.leave_type, day_portion=r.day_portion,
                                status=r.status, late_minutes=r.late_minutes, early_minutes=r.early_minutes,
                                flags=",".join(r.flags) or None))


def process_upload(session: Session, settings: Settings, filename: str, data: bytes, actor: str, replace: bool = False) -> DayUpload:
    rows = read_file(settings, filename, data)
    rules = get_rules(session, settings)
    report_date, results, insights = _analyse(session, rows, rules)
    existing = current_upload(session, report_date)
    if existing and not replace:
        raise AlreadyUploaded(report_date, existing.upload_id)
    if existing:
        existing.is_current = False
    sha = sha256_bytes(data)
    folder = settings.storage.area("uploads") / report_date.isoformat()
    folder.mkdir(parents=True, exist_ok=True)
    stored = folder / f"{sha[:12]}_{safe_filename(filename)}"
    stored.write_bytes(data)
    upload = DayUpload(report_date=report_date, original_filename=safe_filename(filename), stored_path=str(stored), sha256=sha,
                       is_current=True, employees=len(results), insights=json.dumps(insights), rules=rules.model_dump_json(),
                       uploaded_by=actor)
    session.add(upload)
    session.flush()
    _store_rows(session, upload.upload_id, results)
    record_activity(session, "DAY_UPLOAD", "SUCCESS", username=actor,
                    detail={"date": report_date.isoformat(), "employees": len(results), "replaced": existing.upload_id if existing else None})
    session.flush()
    return upload


def recalculate(session: Session, settings: Settings, report_date: date, actor: str) -> DayUpload:
    """Re-run the analysis of a stored file with the current Settings (e.g. after changing rules)."""
    upload = current_upload(session, report_date)
    if upload is None:
        raise LookupError("No upload for that date.")
    data = Path(upload.stored_path).read_bytes()
    return process_upload(session, settings, upload.original_filename, data, actor, replace=True)


def rows_for(session: Session, upload_id: int) -> list[dict]:
    out = []
    for e in session.scalars(select(EmployeeDay).where(EmployeeDay.upload_id == upload_id).order_by(EmployeeDay.category, EmployeeDay.employee_code)):
        out.append({"code": e.employee_code, "name": e.employee_name or "", "category": e.category, "shift": e.shift_name or "",
                    "in_time": e.in_time, "out_time": e.out_time, "punches": e.punches, "work_minutes": e.work_minutes,
                    "work_hours": round(e.work_minutes / 60, 2) if e.work_minutes is not None else None,
                    "leave_type": e.leave_type, "day_portion": e.day_portion, "status": e.status,
                    "status_label": analysis.STATUS_LABEL[e.status], "late_minutes": e.late_minutes,
                    "early_minutes": e.early_minutes, "flags": (e.flags or "").split(",") if e.flags else []})
    return out


# ---------------------------------------------------------------------------- outputs
def excel_bytes(settings: Settings, upload: DayUpload, scope: str, rows: list[dict]) -> bytes:
    return build_excel(settings.app.company, upload.report_date, scope, json.loads(upload.insights), rows, settings.app.date_format)


def dashboard_bytes(settings: Settings, upload: DayUpload, scope: str, rows: list[dict]) -> bytes:
    return dashboard_html(settings.app.company, upload.report_date, scope, json.loads(upload.insights), rows, settings.app.date_format)


def check_scope(upload: DayUpload, scope: str) -> str:
    insights = json.loads(upload.insights)
    if scope != ALL and scope not in insights["categories"]:
        raise LookupError(f"Unknown category '{scope}'.")
    return scope


def email_preview(session: Session, settings: Settings, upload: DayUpload, scope: str) -> tuple[str, str]:
    cfg = get_email_settings(session, settings)
    names = [r.name for r in recipients_by_scope(session).get(scope if scope == ALL else scope.lower(), [])]
    subject, html, _ = email_parts(settings.app.company, upload.report_date, scope, json.loads(upload.insights),
                                   settings.app.date_format, cfg.subject_prefix, names, settings.app.public_url)
    return subject, html


def send_reports(session: Session, settings: Settings, upload: DayUpload, actor: str, scopes: list[str] | None = None) -> list[EmailOutcome]:
    """One email per scope (ALL + each category) to that scope's recipients."""
    cfg = get_email_settings(session, settings)
    insights = json.loads(upload.insights)
    rows = rows_for(session, upload.upload_id)
    by_scope = recipients_by_scope(session)
    outbox = settings.storage.area("outbox") / upload.report_date.isoformat()
    targets = scopes or [ALL] + insights["categories"]
    outcomes = []
    for scope in targets:
        people = by_scope.get(ALL if scope == ALL else scope.lower(), [])
        if not people:
            outcomes.append(EmailOutcome(scope, [], "NO_RECIPIENTS", "Add a recipient for this in Settings."))
            continue
        to = [p.email for p in people]
        subject, html, text = email_parts(settings.app.company, upload.report_date, scope, insights, settings.app.date_format,
                                          cfg.subject_prefix, [p.name for p in people], settings.app.public_url)
        stem = file_stem(upload.report_date, scope)
        attachments = []
        if cfg.attach_excel:
            attachments.append(Attachment(f"{stem}.xlsx", excel_bytes(settings, upload, scope, rows), XLSX))
        if cfg.attach_dashboard:
            attachments.append(Attachment(f"{stem}_dashboard.html", dashboard_bytes(settings, upload, scope, rows), "text/html"))
        message = build_message(cfg.sender or "apis-attendance@localhost", to, subject, html, text, attachments)
        try:
            result = send(cfg, message, outbox)
            outcome = EmailOutcome(scope, to, result.status, result.outbox_file)
        except MailError as exc:
            outcome = EmailOutcome(scope, to, "FAILED", str(exc))
        session.add(EmailLog(upload_id=upload.upload_id, scope=scope, recipients=", ".join(to)[:2000], subject=subject[:300],
                             mode="LIVE" if cfg.mode == "live" else "TEST", status=outcome.status,
                             error=outcome.detail if outcome.status == "FAILED" else None,
                             outbox_file=outcome.detail if outcome.status == "SAVED" else None, sent_by=actor))
        outcomes.append(outcome)
    record_activity(session, "REPORT_EMAIL", "FAILED" if any(o.status == "FAILED" for o in outcomes) else "SUCCESS", username=actor,
                    detail={"date": upload.report_date.isoformat(), "mode": cfg.mode,
                            "results": {o.scope: o.status for o in outcomes}})
    session.flush()
    return outcomes


def upload_and_send(session: Session, settings: Settings, filename: str, data: bytes, actor: str, replace: bool = False) -> tuple[DayUpload, list[EmailOutcome] | None]:
    upload = process_upload(session, settings, filename, data, actor, replace)
    cfg = get_email_settings(session, settings)
    return upload, (send_reports(session, settings, upload, actor) if cfg.auto_send else None)
