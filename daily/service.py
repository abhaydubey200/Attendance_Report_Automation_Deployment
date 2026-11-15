"""Upload one day (Pocket HRMS and/or Bizom) -> analyse -> store -> plan one email per recipient (daily.mail)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from core.config import Rules, Settings
from daily import analysis, bizom, employees
from daily.analysis import FileError
from daily.excel_report import build_excel
from daily.render import dashboard_html
from daily.settings_store import get_email_settings, get_rules
from database.models.daily import DayUpload, EmployeeDay
from ingestion.checksum import sha256_bytes
from ingestion.file_inspector import inspect_file, safe_filename
from ingestion.file_reader import ReadError, read_raw
from ingestion.reshapers import reshape_attendance_summary
from security.audit import record_activity

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


class AlreadyUploaded(Exception):
    def __init__(self, report_date: date, upload_id: int, kinds: list[str] | None = None) -> None:
        what = " and ".join(SOURCE_LABEL[k] for k in kinds) if kinds else "This day"
        super().__init__(f"{what} for {report_date:%d-%b-%Y} is already uploaded. "
                         f"Upload again with 'Replace' to use this file instead.")
        self.report_date, self.upload_id, self.kinds = report_date, upload_id, kinds or []


SOURCE_LABEL = {"HRMS": "Pocket HRMS file", "BIZOM": "Bizom file"}


@dataclass
class Incoming:
    kind: str                     # HRMS | BIZOM
    filename: str
    data: bytes
    report_date: date
    hrms_rows: list[dict] | None = None
    bizom_day: bizom.BizomDay | None = None


def identify(settings: Settings, filename: str, data: bytes) -> Incoming:
    """Recognise a Pocket HRMS Attendance Summary or a Bizom attendance report by its columns."""
    check = inspect_file(filename, data, tuple(settings.uploads.allowed_extensions), settings.uploads.max_file_size_mb * 1024 * 1024)
    if not check.ok:
        raise FileError(f"{filename}: " + " ".join(check.errors))
    try:
        raw_rows, sheets = read_raw(data, check.file_type)
    except ReadError as exc:
        raise FileError(f"{filename}: {exc}") from exc
    if bizom.looks_like_bizom(raw_rows):
        try:
            day = bizom.parse_rows(raw_rows)
        except bizom.BizomError as exc:
            raise FileError(f"{filename}: {exc}") from exc
        return Incoming("BIZOM", safe_filename(filename), data, day.report_date, bizom_day=day)
    try:
        rows = reshape_attendance_summary(raw_rows, 1, sheets).rows
    except ReadError as exc:
        raise FileError(f"{filename}: {exc} Upload the Pocket HRMS 'Attendance Summary' or the Bizom attendance report.") from exc
    return Incoming("HRMS", safe_filename(filename), data, analysis.report_date_of(rows), hrms_rows=rows)


def read_file(settings: Settings, filename: str, data: bytes) -> list[dict]:
    inc = identify(settings, filename, data)
    if inc.kind != "HRMS":
        raise FileError("This is a Bizom file, not the Pocket HRMS Attendance Summary.")
    return inc.hrms_rows or []


def current_upload(session: Session, report_date: date) -> DayUpload | None:
    return session.scalar(select(DayUpload).where(DayUpload.report_date == report_date, DayUpload.is_current.is_(True)))


def previous_insights(session: Session, report_date: date) -> dict | None:
    prev = session.scalar(select(DayUpload).where(DayUpload.report_date < report_date, DayUpload.is_current.is_(True))
                          .order_by(DayUpload.report_date.desc()))
    return json.loads(prev.insights) if prev else None


def apply_master(session: Session, report_date: date, results: list) -> tuple[list, dict | None]:
    """Fill name/department/HOD/team/manager from the employee master. Employees marked Left
    before this date are dropped. Returns (results, match counts); counts are None with no master."""
    master = employees.master_lookup(session)
    if not master:
        return results, None
    kept, left, missing = [], 0, 0
    for r in results:
        m = master.get(employees.norm_code(r.code))
        if m is None:
            missing += 1
            kept.append(r)
            continue
        if m.status == employees.LEFT and (m.exit_date is None or m.exit_date < report_date):
            left += 1
            continue
        r.name = m.name or r.name
        r.department, r.hod, r.team, r.manager = m.department, m.hod, m.team, m.manager
        kept.append(r)
    in_file = {employees.norm_code(r.code) for r in results}
    absent_from_file = sum(1 for code, m in master.items() if m.status == employees.ACTIVE and code not in in_file)
    return kept, {"matched": len(kept) - missing, "not_in_master": missing, "left_excluded": left,
                  "missing_from_file": absent_from_file}


def _analyse(session: Session, hrms: Incoming | None, bz: Incoming | None, rules: Rules):
    if hrms is not None:
        report_date, results, excluded = analysis.classify(hrms.hrms_rows or [], rules)
    else:
        report_date, results, excluded = bz.report_date, [], 0
    sources: dict = {"hrms": hrms is not None, "bizom_file": bz is not None}
    if bz is not None:
        known = {e.code for e in employees.list_all(session)} | {r.code.upper() for r in results}
        results, sources["bizom"] = analysis.merge_bizom(results, bz.bizom_day, report_date, rules, known)
        excluded += sources["bizom"]["excluded"]
    results, match = apply_master(session, report_date, results)
    if not results:
        raise FileError("No employees left to report for this day (all excluded or marked as Left).")
    insights = analysis.build_insights(report_date, results, rules, excluded + (match or {}).get("left_excluded", 0),
                                       previous_insights(session, report_date), match, sources)
    return report_date, results, insights


def _store_rows(session: Session, upload_id: int, results) -> None:
    for r in results:
        session.add(EmployeeDay(upload_id=upload_id, employee_code=r.code, employee_name=r.name, category=r.category,
                                department=r.department, hod_name=r.hod, team=r.team, reporting_manager=r.manager,
                                shift_name=r.shift, in_time=r.in_time, out_time=r.out_time, punches=r.punches,
                                work_minutes=r.work_minutes, leave_type=r.leave_type, day_portion=r.day_portion,
                                status=r.status, late_minutes=r.late_minutes, early_minutes=r.early_minutes,
                                flags=",".join(r.flags) or None, source=r.source, bizom_status=r.bizom_status,
                                designation=r.designation, hq=r.hq))


def _store_file(settings: Settings, inc: Incoming) -> tuple[str, str]:
    sha = sha256_bytes(inc.data)
    folder = settings.storage.area("uploads") / inc.report_date.isoformat()
    folder.mkdir(parents=True, exist_ok=True)
    stored = folder / f"{inc.kind.lower()}_{sha[:12]}_{inc.filename}"
    stored.write_bytes(inc.data)
    return str(stored), sha


def _stored(settings: Settings, path: str | None, name: str | None) -> Incoming | None:
    if not path:
        return None
    return identify(settings, name or Path(path).name, Path(path).read_bytes())


def process_files(session: Session, settings: Settings, files: list[tuple[str, bytes]], actor: str,
                  replace: bool = False) -> DayUpload:
    """Pocket HRMS and/or Bizom files of ONE day. A file of the other kind already uploaded for that
    day is kept and merged; uploading the same kind again needs ``replace``."""
    if not files:
        raise FileError("Choose a file to upload.")
    incoming = [identify(settings, name, data) for name, data in files]
    kinds = [i.kind for i in incoming]
    if len(set(kinds)) != len(kinds):
        raise FileError("Upload one Pocket HRMS file and/or one Bizom file per day.")
    dates = {i.report_date for i in incoming}
    if len(dates) > 1:
        raise FileError("The files are for different dates: " + ", ".join(f"{i.filename} = {i.report_date:%d-%b-%Y}" for i in incoming))
    report_date = dates.pop()
    existing = current_upload(session, report_date)
    if existing and not replace:
        clash = [k for k in kinds if (existing.stored_path if k == "HRMS" else existing.bizom_path)]
        if clash:
            raise AlreadyUploaded(report_date, existing.upload_id, clash)
    by_kind = {i.kind: i for i in incoming}
    hrms_in, bz_in = by_kind.get("HRMS"), by_kind.get("BIZOM")
    hrms = hrms_in or (_stored(settings, existing.stored_path, existing.original_filename) if existing else None)
    bz = bz_in or (_stored(settings, existing.bizom_path, existing.bizom_filename) if existing else None)

    rules = get_rules(session, settings)
    _, results, insights = _analyse(session, hrms, bz, rules)
    if existing:
        existing.is_current = False
    upload = DayUpload(report_date=report_date, is_current=True, employees=len(results), insights=json.dumps(insights),
                       rules=rules.model_dump_json(), uploaded_by=actor)
    if hrms_in:
        upload.stored_path, upload.sha256 = _store_file(settings, hrms_in)
        upload.original_filename = hrms_in.filename
    elif existing:
        upload.stored_path, upload.sha256, upload.original_filename = existing.stored_path, existing.sha256, existing.original_filename
    if bz_in:
        upload.bizom_path, upload.bizom_sha256 = _store_file(settings, bz_in)
        upload.bizom_filename = bz_in.filename
    elif existing:
        upload.bizom_path, upload.bizom_sha256, upload.bizom_filename = existing.bizom_path, existing.bizom_sha256, existing.bizom_filename
    session.add(upload)
    session.flush()
    _store_rows(session, upload.upload_id, results)
    record_activity(session, "DAY_UPLOAD", "SUCCESS", username=actor,
                    detail={"date": report_date.isoformat(), "employees": len(results), "files": kinds,
                            "replaced": existing.upload_id if existing else None})
    session.flush()
    return upload


def process_upload(session: Session, settings: Settings, filename: str, data: bytes, actor: str, replace: bool = False) -> DayUpload:
    return process_files(session, settings, [(filename, data)], actor, replace)


def recalculate(session: Session, settings: Settings, report_date: date, actor: str) -> DayUpload:
    """Re-run the analysis of the stored files with the current Settings and employee master."""
    upload = current_upload(session, report_date)
    if upload is None:
        raise LookupError("No upload for that date.")
    files = [(name, Path(path).read_bytes()) for name, path in ((upload.original_filename, upload.stored_path),
                                                                 (upload.bizom_filename, upload.bizom_path)) if path]
    return process_files(session, settings, files, actor, replace=True)


def has_both(upload: DayUpload) -> bool:
    return bool(upload.stored_path and upload.bizom_path)


def rows_for(session: Session, upload_id: int) -> list[dict]:
    out = []
    for e in session.scalars(select(EmployeeDay).where(EmployeeDay.upload_id == upload_id).order_by(EmployeeDay.category, EmployeeDay.employee_code)):
        out.append({"code": e.employee_code, "name": e.employee_name or "", "category": e.category, "shift": e.shift_name or "",
                    "department": e.department or "", "hod": e.hod_name or "", "team": e.team or "",
                    "manager": e.reporting_manager or "", "source": e.source or "HRMS", "bizom_status": e.bizom_status or "",
                    "designation": e.designation or "", "hq": e.hq or "",
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
    if scope not in insights["scopes"]:
        raise LookupError(f"Unknown report '{scope}'.")
    return scope


def plan_and_maybe_send(session: Session, settings: Settings, upload: DayUpload, actor: str) -> tuple[list, str | None]:
    """Plan the day's emails (one per recipient). Send them now only when approval is off and auto-send is on.
    Returns (mail items, note for the user)."""
    from daily import mail

    cfg = get_email_settings(session, settings)
    if cfg.wait_for_bizom and not has_both(upload):
        missing = "Bizom" if upload.stored_path else "Pocket HRMS"
        return [], f"Waiting for the {missing} file of this day; the emails are prepared once it is uploaded."
    items = mail.build_plan(session, settings, upload, actor)
    pending = [i for i in items if i.status == mail.PENDING]
    if cfg.approval_required:
        return items, f"{len(pending)} email(s) ready - review and approve them on the Approve emails screen."
    if not cfg.auto_send:
        return items, "Automatic sending is off: send from the Approve emails screen."
    mail.send_items(session, settings, pending, actor)
    return items, None


def upload_files_and_send(session: Session, settings: Settings, files: list[tuple[str, bytes]], actor: str,
                          replace: bool = False) -> tuple[DayUpload, list, str | None]:
    """Upload -> analyse -> plan emails -> (send unless approval is required). Returns (upload, mail items, note)."""
    upload = process_files(session, settings, files, actor, replace)
    items, note = plan_and_maybe_send(session, settings, upload, actor)
    return upload, items, note


def upload_and_send(session: Session, settings: Settings, filename: str, data: bytes, actor: str,
                    replace: bool = False) -> tuple[DayUpload, list]:
    upload, items, _ = upload_files_and_send(session, settings, [(filename, data)], actor, replace)
    return upload, items
