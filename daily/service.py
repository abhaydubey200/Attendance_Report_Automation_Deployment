"""Upload one day (Pocket HRMS Attendance Summary + Permission Report + On Duty Report) -> analyse -> store -> plan one
email per recipient (daily.mail). Pocket HRMS is the only data source."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from core.config import Rules, Settings
from daily import analysis, employees, onduty, permissions
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
        verb, files = ("are", "these files") if kinds and len(kinds) > 1 else ("is", "this file")
        super().__init__(f"{what} for {report_date:%d-%b-%Y} {verb} already uploaded. "
                         f"Upload again with 'Replace' to use {files} instead.")
        self.report_date, self.upload_id, self.kinds = report_date, upload_id, kinds or []


SOURCE_LABEL = {"HRMS": "Pocket HRMS Attendance Summary", "PERMISSION": "Pocket HRMS Permission Report",
                "ONDUTY": "Pocket HRMS On Duty Report"}
EXTRA_KINDS = ("PERMISSION", "ONDUTY")     # reports that may cover several days; they go with a day's Attendance Summary
# DayUpload columns of each file kind: (filename, stored path, sha256)
FILE_COLS = {"HRMS": ("original_filename", "stored_path", "sha256"),
             "PERMISSION": ("permission_filename", "permission_path", "permission_sha256"),
             "ONDUTY": ("onduty_filename", "onduty_path", "onduty_sha256")}


@dataclass
class Incoming:
    kind: str                     # HRMS | PERMISSION | ONDUTY
    filename: str
    data: bytes
    report_date: date | None      # None: a Permission / On Duty Report covering several days (or none)
    hrms_rows: list[dict] | None = None
    permission_day: permissions.PermissionDay | None = None
    onduty_day: onduty.OnDutyDay | None = None

    @property
    def dates(self) -> set[date]:
        if self.kind == "PERMISSION":
            return self.permission_day.dates
        if self.kind == "ONDUTY":
            return self.onduty_day.dates
        return {self.report_date} if self.report_date else set()


def identify(settings: Settings, filename: str, data: bytes) -> Incoming:
    """Recognise a Pocket HRMS Attendance Summary, Permission Report or On Duty Report by its columns."""
    check = inspect_file(filename, data, tuple(settings.uploads.allowed_extensions), settings.uploads.max_file_size_mb * 1024 * 1024)
    if not check.ok:
        raise FileError(f"{filename}: " + " ".join(check.errors))
    try:
        raw_rows, sheets = read_raw(data, check.file_type)
    except ReadError as exc:
        raise FileError(f"{filename}: {exc}") from exc
    if permissions.looks_like_permission(raw_rows):
        try:
            day = permissions.parse_rows(raw_rows)
        except permissions.PermissionError_ as exc:
            raise FileError(f"{filename}: {exc}") from exc
        dates = day.dates
        return Incoming("PERMISSION", safe_filename(filename), data, next(iter(dates)) if len(dates) == 1 else None,
                        permission_day=day)
    if onduty.looks_like_onduty(raw_rows):
        try:
            od = onduty.parse_rows(raw_rows)
        except permissions.PermissionError_ as exc:
            raise FileError(f"{filename}: {exc}") from exc
        dates = od.dates
        return Incoming("ONDUTY", safe_filename(filename), data, next(iter(dates)) if len(dates) == 1 else None, onduty_day=od)
    if check.file_type == "html":
        raise FileError(f"{filename}: this .xls is not a Pocket HRMS On Duty Report. Save other reports as .xlsx.")
    if any({"employee_id", "user_name"} <= {str(c).strip().lower() for c in row} for row in raw_rows[:15]):
        raise FileError(f"{filename}: this is a Bizom file. Bizom is no longer used - Pocket HRMS is the only source.")
    try:
        rows = reshape_attendance_summary(raw_rows, 1, sheets).rows
    except ReadError as exc:
        raise FileError(f"{filename}: {exc} Upload the Pocket HRMS 'Attendance Summary', 'Permission Report' or "
                        f"'On Duty Report'.") from exc
    return Incoming("HRMS", safe_filename(filename), data, analysis.report_date_of(rows), hrms_rows=rows)


def read_file(settings: Settings, filename: str, data: bytes) -> list[dict]:
    inc = identify(settings, filename, data)
    if inc.kind != "HRMS":
        raise FileError(f"This is the {SOURCE_LABEL[inc.kind]}, not the Pocket HRMS Attendance Summary.")
    return inc.hrms_rows or []


def current_upload(session: Session, report_date: date) -> DayUpload | None:
    return session.scalar(select(DayUpload).where(DayUpload.report_date == report_date, DayUpload.is_current.is_(True)))


def previous_insights(session: Session, report_date: date) -> dict | None:
    prev = session.scalar(select(DayUpload).where(DayUpload.report_date < report_date, DayUpload.is_current.is_(True))
                          .order_by(DayUpload.report_date.desc()))
    return json.loads(prev.insights) if prev else None


def apply_master(session: Session, report_date: date, results: list,
                 out_of_scope: list[str] | None = None) -> tuple[list, dict | None]:
    """Fill name/department/HOD/team/manager from the employee master. Employees marked Left
    before this date are dropped, and so are staff of an out-of-scope category (field sales) who are not
    in the master. Returns (results, match counts); counts are None with no master."""
    master = employees.master_lookup(session)
    if not master:
        return results, None
    skip_cats = {c.strip().casefold() for c in (out_of_scope or []) if c.strip()}
    kept, left, missing, skipped = [], 0, 0, 0
    for r in results:
        m = master.get(employees.norm_code(r.code))
        if m is None and (r.category or "").strip().casefold() in skip_cats:
            skipped += 1
            continue
        if m is None:
            missing += 1
            r.department = None                     # grouped as "Not in employee master" (no duplicate spellings)
            kept.append(r)
            continue
        if m.status == employees.LEFT and (m.exit_date is None or m.exit_date < report_date):
            left += 1
            continue
        r.name = m.name or r.name
        r.department = m.department or r.department            # the file's Department fills a blank in the master
        r.hod, r.team, r.manager = m.hod, m.team, m.manager
        kept.append(r)
    in_file = {employees.norm_code(r.code) for r in results}
    absent_from_file = sum(1 for code, m in master.items() if m.status == employees.ACTIVE and code not in in_file)
    return kept, {"matched": len(kept) - missing, "not_in_master": missing, "left_excluded": left,
                  "missing_from_file": absent_from_file, "out_of_scope": skipped}


def _analyse(session: Session, hrms: Incoming | None, perm: Incoming | None, rules: Rules, od: Incoming | None = None):
    if hrms is None:
        raise FileError("Upload the Pocket HRMS Attendance Summary of this day first (the Permission Report and the "
                        "On Duty Report go with it).")
    report_date, results, excluded = analysis.classify(hrms.hrms_rows or [], rules)
    sources: dict = {"hrms": True, "permission_file": perm is not None, "onduty_file": od is not None}
    if perm is not None:
        sources["permissions"] = analysis.apply_permissions(results, perm.permission_day, report_date, rules)
    if od is not None:
        sources["onduty"] = analysis.apply_onduty(results, od.onduty_day, report_date, rules)
    results, match = apply_master(session, report_date, results, rules.out_of_scope_categories)
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
                                flags=",".join(r.flags) or None, source=r.source, permission=r.permission,
                                on_duty=r.on_duty))


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
                  replace: bool = False, kinds: list[str | None] | None = None) -> DayUpload:
    """Attendance Summary, Permission Report and/or On Duty Report of ONE day. A file of another kind already uploaded
    for that day is kept and merged; uploading the same kind again needs ``replace``."""
    if not files:
        raise FileError("Choose a file to upload.")
    incoming = [identify(settings, name, data) for name, data in files]
    for inc, wanted in zip(incoming, kinds or []):
        if wanted and inc.kind != wanted:
            raise FileError(f"{inc.filename} is a {SOURCE_LABEL[inc.kind]}, but it was put in the {SOURCE_LABEL[wanted]} box.")
    kinds = [i.kind for i in incoming]
    if len(set(kinds)) != len(kinds):
        raise FileError("Upload at most one Attendance Summary, one Permission Report and one On Duty Report per day.")
    hrms_date = next((i.report_date for i in incoming if i.kind == "HRMS"), None)
    for inc in incoming:
        if inc.kind not in EXTRA_KINDS:
            continue
        if hrms_date is not None:
            if hrms_date in inc.dates:
                inc.report_date = hrms_date      # a multi-day report that includes the day is fine
            continue
        if inc.report_date is None:
            # A report covering several days, uploaded without the Attendance Summary: use the one of its days that
            # has attendance uploaded.
            known = [d for d in sorted(inc.dates) if current_upload(session, d) is not None]
            if len(known) != 1:
                raise FileError(f"{inc.filename}: the {SOURCE_LABEL[inc.kind]} covers {len(inc.dates)} "
                                f"date(s) - upload it together with that day's Attendance Summary.")
            inc.report_date = known[0]
    if any(i.report_date is None for i in incoming):
        raise FileError("The files are for different dates: " + ", ".join(
            f"{i.filename} = {i.report_date:%d-%b-%Y}" if i.report_date else f"{i.filename} = other dates" for i in incoming))
    dates = {i.report_date for i in incoming}
    if len(dates) != 1:
        raise FileError("The files are for different dates: " + ", ".join(f"{i.filename} = {i.report_date:%d-%b-%Y}" for i in incoming))
    report_date = dates.pop()
    existing = current_upload(session, report_date)
    if existing and not replace:
        clash = [k for k in kinds if getattr(existing, FILE_COLS[k][1])]
        if clash:
            raise AlreadyUploaded(report_date, existing.upload_id, clash)
    by_kind = {i.kind: i for i in incoming}

    def use(kind: str) -> Incoming | None:
        if kind in by_kind:
            return by_kind[kind]
        if existing is None:
            return None
        name_col, path_col, _ = FILE_COLS[kind]
        return _stored(settings, getattr(existing, path_col), getattr(existing, name_col))

    hrms, perm, od = use("HRMS"), use("PERMISSION"), use("ONDUTY")
    rules = get_rules(session, settings)
    _, results, insights = _analyse(session, hrms, perm, rules, od)
    if existing:
        existing.is_current = False
    upload = DayUpload(report_date=report_date, is_current=True, employees=len(results), insights=json.dumps(insights),
                       rules=rules.model_dump_json(), uploaded_by=actor)
    for kind, (name_col, path_col, sha_col) in FILE_COLS.items():
        if kind in by_kind:
            path, sha = _store_file(settings, by_kind[kind])
            setattr(upload, path_col, path)
            setattr(upload, sha_col, sha)
            setattr(upload, name_col, by_kind[kind].filename)
        elif existing:
            for col in (name_col, path_col, sha_col):
                setattr(upload, col, getattr(existing, col))
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
    files = [(getattr(upload, name_col) or Path(getattr(upload, path_col)).name, Path(getattr(upload, path_col)).read_bytes())
             for name_col, path_col, _ in FILE_COLS.values() if getattr(upload, path_col)]
    return process_files(session, settings, files, actor, replace=True)


def has_both(upload: DayUpload) -> bool:
    return bool(upload.stored_path and upload.permission_path)


def rows_for(session: Session, upload_id: int) -> list[dict]:
    out = []
    for e in session.scalars(select(EmployeeDay).where(EmployeeDay.upload_id == upload_id).order_by(EmployeeDay.category, EmployeeDay.employee_code)):
        out.append({"code": e.employee_code, "name": e.employee_name or "", "category": e.category, "shift": e.shift_name or "",
                    "department": e.department or "", "hod": e.hod_name or "", "team": e.team or "",
                    "manager": e.reporting_manager or "", "source": e.source or "HRMS", "permission": e.permission or "",
                    "in_time": e.in_time, "out_time": e.out_time, "punches": e.punches, "work_minutes": e.work_minutes,
                    "work_hours": round(e.work_minutes / 60, 2) if e.work_minutes is not None else None,
                    "on_duty": e.on_duty or "", "leave_type": e.leave_type, "day_portion": e.day_portion, "status": e.status,
                    "status_label": analysis.STATUS_LABEL[e.status], "late_minutes": e.late_minutes,
                    "early_minutes": e.early_minutes, "flags": (e.flags or "").split(",") if e.flags else []})
    return out


# ---------------------------------------------------------------------------- outputs
def excel_bytes(settings: Settings, upload: DayUpload, scope: str, rows: list[dict]) -> bytes:
    return build_excel(settings.app.company, upload.report_date, scope, json.loads(upload.insights), rows, settings.app.date_format)


def dashboard_bytes(settings: Settings, upload: DayUpload, scope: str, rows: list[dict], session: Session | None = None) -> bytes:
    """With a session, Key insights compare with the previous uploaded day."""
    prev = None
    if session is not None:
        prev = session.scalar(select(DayUpload).where(DayUpload.report_date < upload.report_date, DayUpload.is_current.is_(True))
                              .order_by(DayUpload.report_date.desc()))
    return dashboard_html(settings.app.company, upload.report_date, scope, json.loads(upload.insights), rows, settings.app.date_format,
                          rows_for(session, prev.upload_id) if prev else None, prev.report_date if prev else None)


def check_scope(upload: DayUpload, scope: str) -> str:
    insights = json.loads(upload.insights)
    if scope not in insights["scopes"]:
        raise LookupError(f"Unknown report '{scope}'.")
    return scope


AUTO, MANUAL = "auto", "manual"


def default_send_mode(cfg) -> str:
    """Settings default: manual (approve first) when preview mode is on or auto-send is off."""
    return MANUAL if cfg.approval_required or not cfg.auto_send else AUTO


def plan_and_maybe_send(session: Session, settings: Settings, upload: DayUpload, actor: str,
                        mode: str | None = None) -> tuple[list, str | None]:
    """Plan the day's emails (one per recipient). mode 'auto' sends them now; 'manual' leaves them on the
    Approve emails screen; None uses the Settings default. Returns (mail items, note for the user)."""
    from daily import mail

    cfg = get_email_settings(session, settings)
    if mode not in (None, AUTO, MANUAL):
        raise FileError("Email sending must be 'auto' or 'manual'.")
    mode = mode or default_send_mode(cfg)
    if cfg.wait_for_permission and not has_both(upload):
        return [], ("Waiting for the Permission Report of this day; the emails are prepared once it is uploaded "
                    "(or switch this off in Settings).")
    items = mail.build_plan(session, settings, upload, actor)
    pending = [i for i in items if i.status == mail.PENDING]
    if mode == MANUAL:
        return items, f"{len(pending)} email(s) ready - review and approve them on the Approve emails screen."
    mail.send_items(session, settings, pending, actor)
    return items, None


def upload_files_and_send(session: Session, settings: Settings, files: list[tuple[str, bytes]], actor: str,
                          replace: bool = False, mode: str | None = None,
                          kinds: list[str | None] | None = None) -> tuple[DayUpload, list, str | None]:
    """Upload -> analyse -> plan emails -> send now (auto) or wait for approval (manual).
    Returns (upload, mail items, note)."""
    upload = process_files(session, settings, files, actor, replace, kinds)
    items, note = plan_and_maybe_send(session, settings, upload, actor, mode)
    return upload, items, note


def upload_and_send(session: Session, settings: Settings, filename: str, data: bytes, actor: str,
                    replace: bool = False) -> tuple[DayUpload, list]:
    upload, items, _ = upload_files_and_send(session, settings, [(filename, data)], actor, replace)
    return upload, items
