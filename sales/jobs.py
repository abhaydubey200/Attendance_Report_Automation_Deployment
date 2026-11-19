"""Field Sales jobs: the daily run from the Field Sales inbox folder (Task Scheduler) and the job history.

Same safety rules as Module 1's daily job: one run at a time (lock), every run recorded, HR alerted when it fails, and
running it again never sends anything twice. Processed Bizom files are DELETED from the inbox (they hold phone numbers,
photos and GPS); only their name and fingerprint are kept with the day.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from core.config import Settings
from core.timeutils import now_utc
from daily.jobs import JobLocked, job_lock, yesterday_ist  # noqa: F401  (shared helpers; JobLocked re-exported)
from database.connection import session_scope
from database.models.sales import SalesJobRun
from ingestion.checksum import sha256_bytes
from sales.util import utc_iso
from sales import bizom, mail, service
from sales.config import get_email, get_rules

RUNNING, SUCCESS, PARTIAL, FAILED = "RUNNING", "SUCCESS", "PARTIAL", "FAILED"
FILE_TYPES = (".csv", ".xlsx")


def inbox_dir(settings: Settings) -> Path:
    return settings.storage.area("sales_inbox")


def start(session: Session, job: str, target: str | None, trigger: str, actor: str) -> SalesJobRun:
    stale = now_utc() - timedelta(minutes=settings_lock_minutes(session))
    for r in session.scalars(select(SalesJobRun).where(SalesJobRun.status == RUNNING, SalesJobRun.started_at < stale)):
        r.status, r.finished_at, r.error = FAILED, now_utc(), "Abandoned (the process stopped before finishing)."
    run = SalesJobRun(job=job, target=target, trigger=trigger, status=RUNNING, started_by=actor)
    session.add(run)
    session.flush()
    return run


def settings_lock_minutes(_session: Session) -> int:
    from core.config import get_settings
    return get_settings().jobs.lock_stale_minutes


def finish(session: Session, run: SalesJobRun, status: str, summary: dict, error: str | None = None) -> None:
    run.status, run.finished_at = status, now_utc()
    run.summary, run.error = json.dumps(summary, default=str), (error or None) and error[:1000]
    session.flush()


def run_dict(r: SalesJobRun) -> dict:
    return {"id": r.id, "job": r.job, "target": r.target, "trigger": r.trigger, "status": r.status,
            "summary": json.loads(r.summary) if r.summary else None, "error": r.error, "started_by": r.started_by,
            "started_at": utc_iso(r.started_at), "finished_at": utc_iso(r.finished_at),
            "seconds": round((r.finished_at - r.started_at).total_seconds()) if r.finished_at else None}


def history(session: Session, limit: int = 100) -> list[dict]:
    return [run_dict(r) for r in session.scalars(select(SalesJobRun).order_by(SalesJobRun.id.desc()).limit(limit))]


@dataclass
class InboxFile:
    path: Path
    kind: str
    day: date
    data: bytes


def scan(inbox: Path, rules) -> tuple[list[InboxFile], list[str]]:
    files, rejected = [], []
    if not inbox.is_dir():
        return files, [f"Inbox folder not found: {inbox}"]
    for p in sorted(inbox.iterdir(), key=lambda x: x.stat().st_mtime):
        if not p.is_file() or p.suffix.lower() not in FILE_TYPES or p.name.startswith("~$"):
            continue
        data = p.read_bytes()
        try:
            rows = bizom.read_rows(data, p.name)
            kind = bizom.kind_of(rows)
            if kind is None:
                rejected.append(f"{p.name}: not a Bizom Attendance, Attendance & EOD or Call Variance report.")
                continue
            day = bizom.parse(rows, short_call_seconds=rules.short_call_seconds, far_call_m=rules.far_call_m,
                              max_speed_kmh=rules.max_speed_kmh, day_end=rules.calls_after).report_date
        except bizom.BizomError as exc:
            rejected.append(f"{p.name}: {exc}")
            continue
        files.append(InboxFile(p, kind, day, data))
    return files, rejected


def run_daily(settings: Settings, engine, day: date | None = None, send: bool | None = None, trigger: str = "SCHEDULED",
              actor: str = "scheduler") -> dict:
    """Yesterday's Bizom files (or `day`'s) from the inbox -> count the day -> prepare the emails -> send them when
    'auto send' is on (Settings) or `send` is True. Safe to run again."""
    day = day or yesterday_ist()
    inbox = inbox_dir(settings)
    inbox.mkdir(parents=True, exist_ok=True)
    with job_lock(settings, "sales_daily"):
        with session_scope(engine) as s:
            run_id = start(s, "DAILY", day.isoformat(), trigger, actor).id
        summary: dict = {"date": day.isoformat(), "inbox": str(inbox)}
        status = FAILED
        try:
            with session_scope(engine) as s:
                status, summary = _daily(s, settings, day, inbox, send, actor, summary)
                finish(s, s.get(SalesJobRun, run_id), status, summary, summary.get("problem"))
        except Exception as exc:
            with session_scope(engine) as s:
                finish(s, s.get(SalesJobRun, run_id), FAILED, summary, f"{type(exc).__name__}: {exc}")
            _alert(settings, engine, f"Field Sales daily {day:%d-%b-%Y}: failed", f"{type(exc).__name__}: {exc}")
            raise
        if status == FAILED:
            summary["alert"] = _alert(settings, engine, f"Field Sales daily {day:%d-%b-%Y}: failed", summary.get("problem") or "")
    return {"run_id": run_id, "status": status, **summary}


def _daily(s: Session, settings: Settings, day: date, inbox: Path, send: bool | None, actor: str, summary: dict) -> tuple[str, dict]:
    files, rejected = scan(inbox, get_rules(s))
    if rejected:
        summary["rejected_files"] = rejected
    todays = {}
    for f in files:                                          # newest file of each kind for the day
        if f.day == day:
            todays[f.kind] = f
    existing = service.current_upload(s, day)
    att = todays.get(bizom.ATTENDANCE)
    if existing is None and att is None:
        summary["problem"] = f"No Bizom Attendance report for {day:%d-%b-%Y} in {inbox}."
        return FAILED, summary
    if att is not None:
        stored = set((existing.sha256 or "").split(",")) if existing else set()
        fresh = [f for f in todays.values() if sha256_bytes(f.data)[:40] not in stored]
        if fresh:
            up = service.process(s, [(f.path.name, f.data) for f in todays.values()], actor, replace=existing is not None)
            summary["processed"] = [f.path.name for f in todays.values()]
        else:
            up, summary["processed"] = existing, []
        for f in todays.values():                            # raw Bizom files hold phones / photos / GPS: not kept
            f.path.unlink(missing_ok=True)
    else:
        up, summary["processed"] = existing, []
        if todays:
            summary["note"] = "EOD / Call Variance files need the Attendance report of the same day in the inbox too; left in the inbox."
    summary["people"] = up.people
    cfg = get_email(s)
    items = mail.items_for(s, day)
    do_send = cfg.auto_send if send is None else send
    sent = []
    if do_send:
        sent = mail.send_items(s, [i for i in items if i.status in (mail.PENDING, mail.FAILED)], actor, settings.storage.area("sales_outbox"))
    summary["emails"] = {k: sum(1 for i in items if i.status == k) for k in {i.status for i in items}}
    summary["sent_now"] = len(sent)
    summary["send"] = "auto" if do_send else "waiting for approval"
    return (PARTIAL if any(i.status == mail.FAILED for i in items) else SUCCESS), summary


def _alert(settings: Settings, engine, subject: str, body: str) -> str | None:
    try:
        from daily.jobs import alert
        with session_scope(engine) as s:
            return alert(s, settings, subject, body)
    except Exception as exc:  # an alert must never hide the real failure
        return f"alert not sent: {exc}"
