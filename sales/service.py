"""Upload a Bizom day: read the files, count the day, store the results and plan the emails.

The raw Bizom files are NOT kept (they hold phone numbers, photos and GPS); only each file's name and fingerprint.
"""

from __future__ import annotations

import json
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from database.models.sales import SalesDayUpload, SalesEmployee, SalesEmployeeDay, SalesMailItem
from ingestion.checksum import sha256_bytes
from sales.util import utc_iso
from sales import analysis, bizom, geo, mail
from sales.config import get_rules

MAX_MB = 25


class UploadError(ValueError):
    """Shown to the user as-is."""


class AlreadyUploaded(UploadError):
    def __init__(self, day: date):
        super().__init__(f"{day:%d-%b-%Y} is already uploaded. Upload again with 'replace' to recount it.")
        self.day = day


def current_upload(session: Session, day: date) -> SalesDayUpload | None:
    return session.scalar(select(SalesDayUpload).where(SalesDayUpload.report_date == day, SalesDayUpload.is_current.is_(True)))


def read_files(files: list[tuple[str, bytes]], session: Session) -> dict[str, tuple[str, bytes, bizom.BizomFile]]:
    rules = get_rules(session)
    found: dict[str, tuple[str, bytes, bizom.BizomFile]] = {}
    for name, data in files:
        if len(data) > MAX_MB * 1024 * 1024:
            raise UploadError(f"{name}: larger than {MAX_MB} MB.")
        try:
            rows = bizom.read_rows(data, name)
            kind = bizom.kind_of(rows)
            if kind is None:
                raise UploadError(f"{name}: not a Bizom Attendance, Attendance & EOD or Call Variance report.")
            if kind == bizom.HISTORY:
                raise UploadError(f"{name}: this is Bizom's multi-day attendance history - import it under 'Location history' instead.")
            if kind in found:
                raise UploadError(f"Two {bizom.LABEL[kind]}s were chosen ({found[kind][0]} and {name}); upload one of each.")
            parsed = bizom.parse(rows, short_call_seconds=rules.short_call_seconds, far_call_m=rules.far_call_m,
                                 max_speed_kmh=rules.max_speed_kmh, day_end=rules.calls_after)
        except bizom.BizomError as exc:
            raise UploadError(f"{name}: {exc}") from exc
        found[kind] = (name, data, parsed)
    if bizom.ATTENDANCE not in found:
        raise UploadError("The Bizom Attendance report is required (the EOD and Call Variance reports are optional).")
    dates = {k: v[2].report_date for k, v in found.items()}
    if len(set(dates.values())) > 1:
        raise UploadError("The files are for different dates: " + ", ".join(f"{bizom.LABEL[k]} = {d:%d-%b-%Y}" for k, d in dates.items()))
    return found


def process(session: Session, files: list[tuple[str, bytes]], actor: str, replace: bool = False, plan_mail: bool = True,
            rescore: bool = True) -> SalesDayUpload:
    """plan_mail=False for past days loaded as training data (no emails); rescore=False when the caller rescores once at the end."""
    found = read_files(files, session)
    att = found[bizom.ATTENDANCE][2]
    day = att.report_date
    existing = current_upload(session, day)
    if existing and not replace:
        raise AlreadyUploaded(day)
    staff = list(session.scalars(select(SalesEmployee)))
    result = analysis.analyse(att, found.get(bizom.EOD, (None, None, None))[2], found.get(bizom.CALLS, (None, None, None))[2],
                              staff, get_rules(session))
    if existing:
        existing.is_current = False
        for old in session.scalars(select(SalesMailItem).where(SalesMailItem.report_date == day, SalesMailItem.status.in_(mail.REPLACEABLE))):
            old.status, old.note = mail.SUPERSEDED, "Replaced by a newer upload of this day."
    up = SalesDayUpload(report_date=day, is_current=True, people=len(result.people), summary=json.dumps(result.summary),
                        attendance_file=found[bizom.ATTENDANCE][0][:255],
                        eod_file=found.get(bizom.EOD, ("",))[0][:255] or None, calls_file=found.get(bizom.CALLS, ("",))[0][:255] or None,
                        sha256=",".join(sha256_bytes(v[1])[:40] for v in found.values())[:200], uploaded_by=actor)
    session.add(up)
    session.flush()
    for p in result.people:
        c = p.calls
        session.add(SalesEmployeeDay(
            upload_id=up.upload_id, code=p.code, name=p.name[:200], designation=p.designation, zone=p.zone, manager_name=p.manager_name,
            zonal_name=p.zonal_name, hod_name=p.hod_name, in_master=p.in_master, status=p.status, bizom_status=p.bizom_status,
            leave_type=p.leave_type, attendance_time=p.attendance_time, first_activity=p.first_activity, last_activity=p.last_activity,
            market_minutes=p.market_minutes, km=p.km, eod_time=p.eod_time, attendance_variance_m=p.attendance_variance_m, photo=p.photo,
            calls=c.calls if c else None, productive_calls=c.productive if c else None, short_calls=c.short if c else None,
            telephonic_calls=c.telephonic if c else None, beat_jump_calls=c.beat_jump if c else None, far_calls=c.far if c else None,
            max_call_distance_m=c.max_distance_m if c else None, fast_moves=c.fast_moves if c else None,
            order_value=round(c.order_value, 2) if c else None, flags=",".join(p.flags) or None, photo_url=p.photo_url,
            present_type=p.present_type))
    session.flush()
    geo.store_day(session, up, result.people, found.get(bizom.CALLS, (None, None, None))[2])
    # self-check: Bizom's attendance file read again by a separate reader and compared person by person
    from sales import verify
    rules = get_rules(session)
    left_out = {e.code for e in staff if analysis._match(rules.exclude_codes, e.code)
                or (not rules.include_promoters and analysis.is_promoter(e.code, e.designation, rules))}
    vres = verify.check(day, found[bizom.ATTENDANCE][1], list(session.scalars(select(SalesEmployeeDay).where(
        SalesEmployeeDay.upload_id == up.upload_id))), {e.code: e for e in staff}, result.summary.get("off_day"), left_out)
    summary = json.loads(up.summary)
    summary["verify"] = vres
    up.summary = json.dumps(summary)
    from sales import photos
    photos.register_day(session, up)                      # selfies to check (downloaded later by the photo job)
    from sales import ml
    if rescore:
        ml.rescore(session, day)                          # learned usual places / unusual days / risk scores
    geo.check_day(session, day)
    geo.purge(session)
    if plan_mail:
        mail.plan(session, up)
    return up


def import_history(session: Session, name: str, data: bytes) -> dict:
    if len(data) > 60 * 1024 * 1024:
        raise UploadError(f"{name}: larger than 60 MB.")
    try:
        rows = bizom.read_rows(data, name)
        if bizom.kind_of(rows) != bizom.HISTORY:
            raise UploadError(f"{name}: not Bizom's multi-day AttendanceReport (needs Emp Id, For Date, Attendance Time, IMEI, Location).")
        hist = bizom.parse(rows)
    except bizom.BizomError as exc:
        raise UploadError(f"{name}: {exc}") from exc
    return geo.import_history(session, hist)


def rows_for(session: Session, upload_id: int) -> list[SalesEmployeeDay]:
    return list(session.scalars(select(SalesEmployeeDay).where(SalesEmployeeDay.upload_id == upload_id).order_by(SalesEmployeeDay.name)))


def days(session: Session) -> list[dict]:
    out = []
    for u in session.scalars(select(SalesDayUpload).where(SalesDayUpload.is_current.is_(True)).order_by(SalesDayUpload.report_date.desc())):
        s = json.loads(u.summary)
        out.append({"report_date": u.report_date.isoformat(), "people": u.people, "attendance_pct": s.get("attendance_pct"),
                    "absent": s["counts"].get("ABSENT", 0), "late": s["counts"].get("LATE", 0), "flagged": s.get("people_flagged", 0),
                    "files": s.get("files"), "uploaded_by": u.uploaded_by, "uploaded_at": utc_iso(u.uploaded_at)})
    return out
