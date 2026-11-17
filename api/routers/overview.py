"""Home overview: everything HR needs to see first thing in the morning, in one call."""

from __future__ import annotations

import json
from collections import Counter

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from api.deps import get_db, get_settings, require
from core.config import Settings
from daily import jobs, mail, monthly
from daily.settings_store import get_email_settings
from database.models.daily import DayUpload, Employee, JobRun, MailItem, MonthlySummary
from security.permissions import Perm, Principal

router = APIRouter(tags=["overview"])


def _run(r: JobRun | None) -> dict | None:
    if r is None:
        return None
    return {"job": r.job.lower(), "target": r.target, "status": r.status, "started_at": r.started_at.isoformat(),
            "error": r.error, "summary": json.loads(r.summary) if r.summary else {}}


@router.get("/overview")
def overview(_: Principal = Depends(require(Perm.VIEW_INSIGHTS)), settings: Settings = Depends(get_settings),
             db: Session = Depends(get_db)) -> dict:
    days = list(db.scalars(select(DayUpload).where(DayUpload.is_current.is_(True)).order_by(DayUpload.report_date.desc()).limit(14)))
    latest = days[0] if days else None
    out: dict = {"latest": None, "previous": None, "trend": [], "emails": None, "jobs": {}, "issues": [], "setup": []}
    if latest:
        ins = json.loads(latest.insights)
        s = ins["scopes"]["ALL"]["summary"]
        out["latest"] = {"date": latest.report_date.isoformat(), "employees": s["employees"], "tracked": s["tracked"],
                         "attendance_pct": s["attendance_pct"], "present": s["counts"].get("PRESENT", 0), "absent": s["counts"].get("ABSENT", 0),
                         "late": s["late"], "left_early": s["left_early"], "missing_punch": s["counts"].get("MISSING_PUNCH", 0),
                         "leave": s["counts"].get("LEAVE", 0) + s["counts"].get("HALF_DAY", 0), "avg_in_time": s.get("avg_in_time"),
                         "permission_file": bool(latest.permission_path), "highlights": ins["scopes"]["ALL"]["highlights"][:4]}
        master = ins.get("master") or {}
        if master.get("not_in_master"):
            out["issues"].append({"kind": "warn", "text": f"{master['not_in_master']} people in the attendance file are not in the employee master",
                                  "link": "/employees"})
        if master.get("missing_from_file"):
            out["issues"].append({"kind": "info", "text": f"{master['missing_from_file']} active employee(s) missing from the attendance file",
                                  "link": f"/insights?date={latest.report_date.isoformat()}"})
        if not latest.permission_path:
            out["issues"].append({"kind": "warn", "text": "The Permission Report of this day is not uploaded", "link": "/upload"})
        items = mail.items_for(db, latest.report_date)
        c = Counter(i.status for i in items)
        out["emails"] = {"date": latest.report_date.isoformat(), "total": len(items), "pending": c.get(mail.PENDING, 0) + c.get(mail.TEST_SENT, 0),
                         "sent": c.get(mail.SENT, 0) + c.get(mail.SAVED, 0), "failed": c.get(mail.FAILED, 0), "held": c.get(mail.HELD, 0),
                         "held_notes": sorted({i.note for i in items if i.status == mail.HELD and i.note})}
    for d in reversed(days):
        s = json.loads(d.insights)["scopes"]["ALL"]["summary"]
        out["trend"].append({"date": d.report_date.isoformat(), "attendance_pct": s["attendance_pct"], "absent": s["counts"].get("ABSENT", 0)})
    if len(days) > 1:
        p = json.loads(days[1].insights)["scopes"]["ALL"]["summary"]
        out["previous"] = {"date": days[1].report_date.isoformat(), "attendance_pct": p["attendance_pct"], "absent": p["counts"].get("ABSENT", 0),
                           "late": p["late"], "missing_punch": p["counts"].get("MISSING_PUNCH", 0)}
    for job in ("DAILY", "BACKUP", "MONTHLY"):
        out["jobs"][job.lower()] = _run(db.scalar(select(JobRun).where(JobRun.job == job).order_by(JobRun.id.desc())))
    held = db.scalar(select(func.count()).select_from(Employee).where(Employee.routing_issue.is_not(None), Employee.status == "ACTIVE")) or 0
    if held:
        out["issues"].append({"kind": "warn", "text": f"{held} employee(s) have a routing issue and go to the HR exception list", "link": "/employees"})
    cfg = get_email_settings(db, settings)
    if not cfg.director_emails:
        out["setup"].append({"text": "Director email address is not set", "link": "/settings"})
    if not cfg.hr_emails:
        out["setup"].append({"text": "HR mailbox is not set (exception emails and job alerts go nowhere)", "link": "/settings"})
    if cfg.test_recipient:
        out["setup"].append({"text": f"Testing is ON: every email goes only to {cfg.test_recipient}", "link": "/settings"})
    if cfg.mode != "live":
        out["setup"].append({"text": "Email is in test mode: emails are saved, not delivered", "link": "/settings"})
    m = db.scalar(select(MonthlySummary).order_by(MonthlySummary.month.desc()))
    out["month"] = {"month": m.month, "label": monthly.label(m.month), "attendance_pct": m.attendance_pct, "status": m.status} if m else None
    out["email_mode"] = cfg.mode
    out["employees_active"] = db.scalar(select(func.count()).select_from(Employee).where(Employee.status == "ACTIVE")) or 0
    out["last_backup"] = _run(jobs.last_good_backup(db))
    return out
