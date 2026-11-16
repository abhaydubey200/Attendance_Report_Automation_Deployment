"""Unattended jobs for Windows Task Scheduler: the 09:30 daily run, database backup, job history and alerts.

Each job:
  * takes a lock file so a second start (retry, double trigger) cannot run at the same time;
  * is recorded in ``job_run`` (Automation screen) with its outcome and counts;
  * is idempotent: re-running the daily job re-processes only NEW files and sends only emails that are still
    unsent or failed, so a crash halfway never re-sends what already went out;
  * sends an alert email when it fails (alert_emails, else the HR mailbox).
"""

from __future__ import annotations

import json
import os
import shutil
import socket
import sqlite3
import time
import traceback
from collections import Counter
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from core.config import Settings
from core.timeutils import now_utc
from daily import mail, service
from daily.analysis import FileError
from daily.mailer import MailError, build_message, send
from daily.settings_store import get_email_settings
from database.connection import session_scope
from database.models.daily import JobRun
from ingestion.checksum import sha256_bytes

IST = timezone(timedelta(hours=5, minutes=30))      # India has no daylight saving
RUNNING, SUCCESS, PARTIAL, FAILED, SKIPPED = "RUNNING", "SUCCESS", "PARTIAL", "FAILED", "SKIPPED"
FILE_TYPES = (".xlsx", ".csv")


def yesterday_ist() -> date:
    return datetime.now(IST).date() - timedelta(days=1)


class JobLocked(Exception):
    pass


# ---------------------------------------------------------------------------- lock + history
@contextmanager
def job_lock(settings: Settings, name: str):
    """A lock file in <storage>/locks. A lock older than jobs.lock_stale_minutes is treated as abandoned."""
    folder = settings.storage.area("locks")
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{name}.lock"
    if path.exists() and time.time() - path.stat().st_mtime > settings.jobs.lock_stale_minutes * 60:
        path.unlink(missing_ok=True)
    try:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        raise JobLocked(f"The {name} job is already running (lock {path}).") from None
    try:
        os.write(fd, f"{os.getpid()} {socket.gethostname()} {now_utc().isoformat()}".encode())
        os.close(fd)
        yield
    finally:
        path.unlink(missing_ok=True)


def start_job(session: Session, job: str, target: str | None, trigger: str, actor: str) -> JobRun:
    run = JobRun(job=job, target=target, trigger=trigger, status=RUNNING, started_by=actor)
    session.add(run)
    session.flush()
    return run


def finish_job(session: Session, run: JobRun, status: str, summary: dict | None = None, error: str | None = None) -> JobRun:
    run.status, run.finished_at = status, now_utc()
    run.summary = json.dumps(summary, default=str) if summary else None
    run.error = (error or None) and error[:1000]
    session.flush()
    return run


def mark_abandoned(session: Session, settings: Settings) -> int:
    """RUNNING rows older than the lock timeout belong to a process that died."""
    cutoff = now_utc() - timedelta(minutes=settings.jobs.lock_stale_minutes)
    n = 0
    for run in session.scalars(select(JobRun).where(JobRun.status == RUNNING, JobRun.started_at < cutoff)):
        run.status, run.finished_at, run.error = FAILED, now_utc(), "Abandoned (the process stopped before finishing)."
        n += 1
    return n


def run_dict(r: JobRun) -> dict:
    return {"id": r.id, "job": r.job, "target": r.target, "trigger": r.trigger, "status": r.status,
            "summary": json.loads(r.summary) if r.summary else None, "error": r.error, "started_by": r.started_by,
            "started_at": r.started_at.isoformat(), "finished_at": r.finished_at.isoformat() if r.finished_at else None,
            "seconds": round((r.finished_at - r.started_at).total_seconds()) if r.finished_at else None}


def alert(session: Session, settings: Settings, subject: str, body: str) -> str | None:
    """Tell HR that an unattended job needs attention. Returns how it went (never raises)."""
    cfg = get_email_settings(session, settings)
    to = [a for a in (settings.jobs.alert_emails or cfg.hr_emails) if a]
    if cfg.test_recipient:
        to = [cfg.test_recipient]
    if not to:
        return "no alert address configured"
    msg = build_message(cfg.sender or "attendance@localhost", to, f"[APIS Attendance] {subject}",
                        f"<p>{body}</p><p>See Automation in the attendance app for details.</p>", body, [])
    try:
        return send(cfg, msg, settings.storage.area("outbox") / "alerts").status
    except MailError as exc:
        return f"alert not sent: {exc}"


# ---------------------------------------------------------------------------- daily job
@dataclass
class InboxFile:
    path: Path
    kind: str
    data: bytes
    sha: str
    dates: set[date] = field(default_factory=set)


def scan_inbox(settings: Settings, inbox: Path) -> tuple[list[InboxFile], list[str]]:
    files, rejected = [], []
    if not inbox.is_dir():
        return files, [f"Inbox folder not found: {inbox}"]
    for p in sorted(inbox.iterdir(), key=lambda x: x.stat().st_mtime):
        if not p.is_file() or p.suffix.lower() not in FILE_TYPES or p.name.startswith("~$"):
            continue
        data = p.read_bytes()
        try:
            inc = service.identify(settings, p.name, data)
        except FileError as exc:
            rejected.append(str(exc))
            continue
        dates = inc.permission_day.dates if inc.kind == "PERMISSION" else {inc.report_date}
        files.append(InboxFile(p, inc.kind, data, sha256_bytes(data), dates))
    return files, rejected


def run_daily(settings: Settings, engine, day: date | None = None, inbox: Path | None = None, mode: str | None = None,
              trigger: str = "SCHEDULED", actor: str = "scheduler") -> dict:
    """Yesterday's attendance (or `day`): process new files from the inbox, prepare the emails, verify them and send
    (unless the send mode is manual). Safe to run again: nothing already sent is sent twice."""
    day = day or yesterday_ist()
    inbox = Path(inbox or settings.jobs.inbox_dir)
    with job_lock(settings, "daily"):
        with session_scope(engine) as s:
            mark_abandoned(s, settings)
            run = start_job(s, "DAILY", day.isoformat(), trigger, actor)
            run_id = run.id
        summary: dict = {"date": day.isoformat(), "inbox": str(inbox)}
        try:
            with session_scope(engine) as s:
                status, summary = _daily(s, settings, day, inbox, mode, actor, summary)
            with session_scope(engine) as s:
                finish_job(s, s.get(JobRun, run_id), status, summary, summary.get("problem"))
                if status in (FAILED, PARTIAL):
                    summary["alert"] = alert(s, settings, f"Daily attendance {day:%d-%b-%Y}: {status.lower()}",
                                             summary.get("problem") or "Some emails failed.")
        except Exception as exc:  # recorded and alerted, then re-raised for the exit code
            with session_scope(engine) as s:
                finish_job(s, s.get(JobRun, run_id), FAILED, summary, f"{type(exc).__name__}: {exc}")
                alert(s, settings, f"Daily attendance {day:%d-%b-%Y}: failed", f"{type(exc).__name__}: {exc}")
            raise
    return {"run_id": run_id, "status": status, **summary}


def _daily(s: Session, settings: Settings, day: date, inbox: Path, mode: str | None, actor: str, summary: dict) -> tuple[str, dict]:
    files, rejected = scan_inbox(settings, inbox)
    if rejected:
        summary["rejected_files"] = rejected
    att = [f for f in files if f.kind == "HRMS" and day in f.dates]
    perm = [f for f in files if f.kind == "PERMISSION" and day in f.dates]
    existing = service.current_upload(s, day)
    new = []
    if att and (existing is None or existing.sha256 != att[-1].sha):
        new.append(att[-1])
    if perm and (existing is None or existing.permission_sha256 != perm[-1].sha):
        new.append(perm[-1])
    if existing is None and not att:
        summary["problem"] = f"No Pocket HRMS Attendance Summary for {day:%d-%b-%Y} in {inbox}."
        return FAILED, summary
    if new:
        replace = existing is not None
        up = service.process_files(s, settings, [(f.path.name, f.data) for f in new], actor, replace=replace)
        summary["processed"] = [f.path.name for f in new]
    else:
        up = existing
        summary["processed"] = []
    summary["employees"] = up.employees
    summary["permission_report"] = bool(up.permission_path)
    if not up.permission_path and settings.jobs.permission_required:
        summary["problem"] = f"The Permission Report for {day:%d-%b-%Y} is not in {inbox}; emails not prepared (jobs.permission_required)."
        _move_done(files, new, inbox, day)
        return FAILED, summary

    items = mail.items_for(s, day)
    if new or not items:
        items = mail.build_plan(s, settings, up, actor)
    to_send = [i for i in items if i.status in (mail.PENDING, mail.FAILED)]
    cfg = get_email_settings(s, settings)
    mode = mode or service.default_send_mode(cfg)
    summary["send_mode"] = mode
    # Verify every email and attachment can be produced BEFORE anything is sent.
    for item in to_send:
        mail.render(s, settings, item)
    summary["verified"] = len(to_send)
    if mode == service.AUTO and to_send:
        mail.send_items(s, settings, to_send, actor)
    counts = dict(Counter(i.status for i in mail.items_for(s, day)))
    summary["emails"] = counts
    _move_done(files, new, inbox, day)
    if counts.get(mail.FAILED):
        summary["problem"] = f"{counts[mail.FAILED]} email(s) failed; they are retried on the next run or from Approve emails."
        return PARTIAL, summary
    return SUCCESS, summary


def _move_done(files: list[InboxFile], used: list[InboxFile], inbox: Path, day: date) -> None:
    """Move the day's files out of the inbox (also unchanged re-drops of the same file)."""
    target = inbox / "processed" / day.isoformat()
    for f in files:
        if day in f.dates and f.path.exists():
            target.mkdir(parents=True, exist_ok=True)
            dest = target / f.path.name
            if dest.exists():
                dest = target / f"{f.path.stem}_{int(time.time())}{f.path.suffix}"
            shutil.move(str(f.path), dest)


# ---------------------------------------------------------------------------- backup
def backup(settings: Settings, engine, trigger: str = "SCHEDULED", actor: str = "scheduler") -> dict:
    """Online SQLite backup (consistent while the app runs), integrity-checked, older copies pruned."""
    if settings.database.backend != "sqlite":
        raise RuntimeError("Backups here are for SQLite; back up SQL Server with its own tools.")
    folder = settings.storage.area("backups")
    folder.mkdir(parents=True, exist_ok=True)
    with job_lock(settings, "backup"):
        with session_scope(engine) as s:
            run_id = start_job(s, "BACKUP", date.today().isoformat(), trigger, actor).id
        dest = folder / f"attendance_{datetime.now(IST):%Y%m%d_%H%M%S}.db"
        try:
            src = sqlite3.connect(str(settings.database.path))
            out = sqlite3.connect(str(dest))
            try:
                src.backup(out)
            finally:
                src.close()
            check = out.execute("PRAGMA integrity_check").fetchone()[0]
            out.close()
            if check != "ok":
                raise RuntimeError(f"Backup integrity check failed: {check}")
            cutoff = time.time() - settings.jobs.backup_keep_days * 86400
            pruned = 0
            for old in folder.glob("attendance_*.db"):
                if old != dest and old.stat().st_mtime < cutoff:
                    old.unlink()
                    pruned += 1
            summary = {"file": str(dest), "bytes": dest.stat().st_size, "integrity": check, "pruned": pruned}
            with session_scope(engine) as s:
                finish_job(s, s.get(JobRun, run_id), SUCCESS, summary)
            return {"run_id": run_id, "status": SUCCESS, **summary}
        except Exception as exc:
            dest.unlink(missing_ok=True)
            with session_scope(engine) as s:
                finish_job(s, s.get(JobRun, run_id), FAILED, None, f"{type(exc).__name__}: {exc}")
                alert(s, settings, "Database backup failed", f"{type(exc).__name__}: {exc}")
            raise


def last_good_backup(session: Session) -> JobRun | None:
    return session.scalar(select(JobRun).where(JobRun.job == "BACKUP", JobRun.status == SUCCESS).order_by(JobRun.id.desc()))


def history(session: Session, limit: int = 100) -> list[dict]:
    return [run_dict(r) for r in session.scalars(select(JobRun).order_by(JobRun.id.desc()).limit(limit))]


def format_exc() -> str:
    return traceback.format_exc(limit=3)
