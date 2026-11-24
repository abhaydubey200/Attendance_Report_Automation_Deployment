"""Module 2 - Field Sales attendance (Bizom) API, all under /api/v1/sales. Independent of Module 1's routes."""

from __future__ import annotations

import json
from datetime import date

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from fastapi.responses import HTMLResponse, Response
from pydantic import BaseModel, ValidationError
from sqlalchemy.orm import Session

from api.deps import get_db, get_engine, get_settings, require
from core.config import Settings
from daily.branding import inline_logo_for_browser
from database.models.sales import SalesMailItem
from sales.util import utc_iso
from sales import bizom, geo, jobs, mail, monthly, photos, report, reports, service, staff
from sales.config import SalesEmail, SalesRules, get_email, get_rules, save_email, save_rules
from security.permissions import Perm, Principal

router = APIRouter(prefix="/sales", tags=["sales"])
PREVIEW_CSP = "default-src 'none'; style-src 'unsafe-inline'; img-src data:; sandbox; frame-ancestors 'self'"
DASHBOARD_CSP = "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src data:; sandbox allow-scripts"
XLSX = mail.XLSX


def _upload_or_404(db: Session, d: date):
    up = service.current_upload(db, d)
    if up is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"{d:%d-%b-%Y} has not been uploaded.")
    return up


def _scores(db: Session, d: date) -> dict:
    from sales import ml
    return ml.scores(db, d)


def _checks_and_proof(db: Session, d: date) -> tuple[list[dict], list[dict]]:
    from sales import checks
    found = checks.day_checks(db, d, None)
    return found, checks.proof(db, d, found)


def _checks(db: Session, d: date) -> list[dict]:
    from sales import checks
    return checks.day_checks(db, d, None)


def _day(db: Session, up) -> dict:
    s = json.loads(up.summary)
    rows = service.rows_for(db, up.upload_id)
    view = report.build_view(rows, s, "hr", "HR", up.report_date)
    return {"report_date": up.report_date.isoformat(), "people": up.people, "summary": s,
            "files": {"attendance": up.attendance_file, "eod": up.eod_file, "calls": up.calls_file},
            "uploaded_by": up.uploaded_by, "uploaded_at": utc_iso(up.uploaded_at),
            "rows": view["people"], "warnings": view["warnings"], "teams": view["teams"],
            "mail": [mail.item_dict(i) for i in mail.items_for(db, up.report_date)],
            "geo": {r.code: [geo.GEO[k][0] for k in r.geo_flags.split(",") if k in geo.GEO] for r in rows if r.geo_flags},
            "geo_summary": geo.summary(db, up.report_date),
            "risk": {c: s.risk for c, s in _scores(db, up.report_date).items() if s.risk}}


# ---------------------------------------------------------------- days
@router.get("/days")
def days(_: Principal = Depends(require(Perm.VIEW_INSIGHTS)), db: Session = Depends(get_db)) -> list[dict]:
    return service.days(db)


@router.post("/upload")
async def upload(files: list[UploadFile] = File(...), replace: bool = Form(False),
                 principal: Principal = Depends(require(Perm.UPLOAD_AND_SEND)), db: Session = Depends(get_db)) -> dict:
    if len(files) > 3:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Upload at most three Bizom reports: Attendance, Attendance & EOD, Call Variance.")
    payload = [(f.filename or "bizom.csv", await f.read(service.MAX_MB * 1024 * 1024 + 1)) for f in files]
    try:
        up = service.process(db, payload, principal.username, replace)
    except service.AlreadyUploaded as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from None
    except service.UploadError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from None
    return _day(db, up)


@router.get("/days/{report_date}")
def day(report_date: date, _: Principal = Depends(require(Perm.VIEW_INSIGHTS)), db: Session = Depends(get_db)) -> dict:
    return _day(db, _upload_or_404(db, report_date))


@router.get("/days/{report_date}/pack")
def day_pack(report_date: date, _: Principal = Depends(require(Perm.VIEW_INSIGHTS)), db: Session = Depends(get_db)) -> dict:
    """The last 30 Bizom days for this day's people: trend, team-head scorecard + weekday heatmap, per-person strips."""
    from sales import insights

    up = _upload_or_404(db, report_date)
    rows = service.rows_for(db, up.upload_id)
    return insights.pack(db, up.report_date, {r.code for r in rows},
                         {r.code: report.manager_label(r.manager_name) or "No team head" for r in rows})


@router.get("/days/{report_date}/excel")
def day_excel(report_date: date, _: Principal = Depends(require(Perm.VIEW_INSIGHTS)), db: Session = Depends(get_db)) -> Response:
    up = _upload_or_404(db, report_date)
    v = report.build_view(service.rows_for(db, up.upload_id), json.loads(up.summary), "hr", "HR", up.report_date,
                           *_checks_and_proof(db, up.report_date))
    return Response(report.excel(v), media_type=XLSX, headers={"Content-Disposition": f'attachment; filename="{v["stem"]}.xlsx"'})


@router.get("/days/{report_date}/dashboard")
def day_dashboard(report_date: date, _: Principal = Depends(require(Perm.VIEW_INSIGHTS)), db: Session = Depends(get_db)) -> Response:
    up = _upload_or_404(db, report_date)
    v = report.build_view(service.rows_for(db, up.upload_id), json.loads(up.summary), "company", "HR", up.report_date,
                           *_checks_and_proof(db, up.report_date))
    return Response(report.dashboard(v), media_type="text/html", headers={
        "Content-Disposition": f'attachment; filename="{v["stem"]}_dashboard.html"', "Content-Security-Policy": DASHBOARD_CSP})


# ---------------------------------------------------------------- emails
class ApproveIn(BaseModel):
    ids: list[int] | None = None


def _outbox(settings: Settings):
    return settings.storage.area("sales_outbox")


@router.get("/days/{report_date}/mail")
def day_mail(report_date: date, _: Principal = Depends(require(Perm.VIEW_INSIGHTS)), db: Session = Depends(get_db)) -> dict:
    cfg = get_email(db)
    return {"report_date": report_date.isoformat(), "mode": cfg.mode, "testing": cfg.test_recipient,
            "items": [mail.item_dict(i) for i in mail.items_for(db, report_date)]}


@router.post("/days/{report_date}/mail/plan")
def replan(report_date: date, _: Principal = Depends(require(Perm.UPLOAD_AND_SEND)), db: Session = Depends(get_db)) -> dict:
    up = _upload_or_404(db, report_date)
    for i in mail.items_for(db, report_date):
        if i.status in mail.REPLACEABLE:
            i.status, i.note = mail.SUPERSEDED, "Prepared again."
    mail.plan(db, up)
    return day_mail(report_date, _, db)


@router.post("/days/{report_date}/mail/approve")
def approve(report_date: date, body: ApproveIn, principal: Principal = Depends(require(Perm.UPLOAD_AND_SEND)),
            settings: Settings = Depends(get_settings), db: Session = Depends(get_db)) -> dict:
    todo = [i for i in mail.items_for(db, report_date) if i.status in (mail.PENDING, mail.FAILED) and (body.ids is None or i.id in body.ids)]
    done = mail.send_items(db, todo, principal.username, _outbox(settings))
    return {**day_mail(report_date, principal, db), "sent_now": len(done)}


def _item(db: Session, item_id: int) -> SalesMailItem:
    item = db.get(SalesMailItem, item_id)
    if item is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Email not found.")
    return item


@router.post("/mail/{item_id}/resend")
def resend(item_id: int, principal: Principal = Depends(require(Perm.UPLOAD_AND_SEND)), settings: Settings = Depends(get_settings),
           db: Session = Depends(get_db)) -> dict:
    item = _item(db, item_id)
    mail.send_items(db, [item], principal.username, _outbox(settings), force=True)
    return mail.item_dict(item)


@router.get("/mail/{item_id}/preview", response_class=HTMLResponse)
def preview(item_id: int, _: Principal = Depends(require(Perm.VIEW_INSIGHTS)), db: Session = Depends(get_db)) -> HTMLResponse:
    html, _text, _files = mail.render(db, _item(db, item_id))
    return HTMLResponse(inline_logo_for_browser(html), headers={"Content-Security-Policy": PREVIEW_CSP})


@router.get("/mail/{item_id}/attachment/{kind}")
def attachment(item_id: int, kind: str, _: Principal = Depends(require(Perm.VIEW_INSIGHTS)), db: Session = Depends(get_db)) -> Response:
    _html, _text, files = mail.render(db, _item(db, item_id))
    want = ".xlsx" if kind == "excel" else "_dashboard.html" if kind == "dashboard" else None
    f = next((f for f in files if want and f.filename.endswith(want)), None)
    if f is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Attachment not found.")
    headers = {"Content-Disposition": f'attachment; filename="{f.filename}"'}
    if kind == "dashboard":
        headers["Content-Security-Policy"] = DASHBOARD_CSP
    return Response(f.content, media_type=f.mime, headers=headers)


# ---------------------------------------------------------------- staff list
@router.get("/staff")
def staff_list(_: Principal = Depends(require(Perm.VIEW_INSIGHTS)), db: Session = Depends(get_db)) -> dict:
    from sqlalchemy import select

    from database.models.sales import SalesEmployee
    return {"summary": staff.summary(db), "staff": [staff.to_dict(e) for e in db.scalars(select(SalesEmployee).order_by(SalesEmployee.name))]}


@router.post("/staff/import")
async def staff_import(file: UploadFile = File(...), principal: Principal = Depends(require(Perm.MANAGE_EMPLOYEES)),
                       db: Session = Depends(get_db)) -> dict:
    data = await file.read(10 * 1024 * 1024 + 1)
    try:
        rows = bizom.read_rows(data, file.filename or "staff.xlsx")
        return staff.import_rows(db, [[("" if c is None else str(c)) for c in r] for r in rows], principal.username, file.filename or "upload",
                                 codes=get_rules(db).staff_codes)
    except (bizom.BizomError, staff.StaffError) as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from None


@router.get("/staff/export")
def staff_export(_: Principal = Depends(require(Perm.VIEW_INSIGHTS)), db: Session = Depends(get_db)) -> Response:
    return Response(staff.export_xlsx(db), media_type=XLSX, headers={"Content-Disposition": 'attachment; filename="Field_Sales_Staff.xlsx"'})


class LeftIn(BaseModel):
    exit_date: date | None = None


class StaffIn(BaseModel):
    code: str | None = None
    name: str | None = None
    designation: str | None = None
    zone: str | None = None
    hq: str | None = None
    channel: str | None = None
    manager_name: str | None = None
    manager_email: str | None = None
    asm_name: str | None = None
    asm_email: str | None = None
    zonal_name: str | None = None
    zonal_email: str | None = None
    hod_name: str | None = None
    hod_email: str | None = None
    date_of_joining: str | None = None
    holiday_state: str | None = None


@router.post("/staff")
def staff_add(body: StaffIn, principal: Principal = Depends(require(Perm.MANAGE_EMPLOYEES)), db: Session = Depends(get_db)) -> dict:
    try:
        return staff.to_dict(staff.add(db, body.model_dump(), principal.username))
    except staff.StaffError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from None


@router.put("/staff/{code}")
def staff_edit(code: str, body: StaffIn, principal: Principal = Depends(require(Perm.MANAGE_EMPLOYEES)), db: Session = Depends(get_db)) -> dict:
    try:
        return staff.to_dict(staff.update(db, code, body.model_dump(exclude_unset=True, exclude={"code"}), principal.username))
    except LookupError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not on the staff list.") from None
    except staff.StaffError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from None


@router.post("/staff/{code}/left")
def staff_left(code: str, body: LeftIn, principal: Principal = Depends(require(Perm.MANAGE_EMPLOYEES)), db: Session = Depends(get_db)) -> dict:
    try:
        return staff.to_dict(staff.mark_left(db, code, body.exit_date, principal.username))
    except LookupError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not on the staff list.") from None


@router.post("/staff/{code}/restore")
def staff_restore(code: str, principal: Principal = Depends(require(Perm.MANAGE_EMPLOYEES)), db: Session = Depends(get_db)) -> dict:
    try:
        return staff.to_dict(staff.restore(db, code, principal.username))
    except LookupError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not on the staff list.") from None


# ---------------------------------------------------------------- settings
@router.get("/settings")
def get_settings_(_: Principal = Depends(require(Perm.VIEW_INSIGHTS)), db: Session = Depends(get_db)) -> dict:
    return {"rules": get_rules(db).model_dump(), "email": get_email(db).model_dump()}


@router.put("/settings/rules")
def put_rules(body: dict, principal: Principal = Depends(require(Perm.MANAGE_SETTINGS)), db: Session = Depends(get_db)) -> dict:
    try:
        rules = SalesRules.model_validate({**get_rules(db).model_dump(), **body})
    except ValidationError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, exc.errors()[0]["msg"].removeprefix("Value error, ")) from None
    return save_rules(db, rules, principal.username).model_dump()


@router.put("/settings/email")
def put_email(body: dict, principal: Principal = Depends(require(Perm.MANAGE_SETTINGS)), db: Session = Depends(get_db)) -> dict:
    try:
        email = SalesEmail.model_validate({**get_email(db).model_dump(), **body})
    except ValidationError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, exc.errors()[0]["msg"].removeprefix("Value error, ")) from None
    return save_email(db, email, principal.username).model_dump()


# ---------------------------------------------------------------- reports and email log
def _range(db: Session, start: date | None, end: date | None) -> tuple[date, date]:
    d0, d1 = reports.default_range(db)
    return start or d0, end or d1


def _attendance(db: Session, start, end, q, hod, team) -> dict:
    try:
        return reports.attendance_report(db, *_range(db, start, end), q, hod, team)
    except reports.ReportError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from None


@router.get("/reports/attendance")
def report_attendance(start: date | None = None, end: date | None = None, q: str = "", hod: str = "", team: str = "",
                      _: Principal = Depends(require(Perm.VIEW_INSIGHTS)), db: Session = Depends(get_db)) -> dict:
    return _attendance(db, start, end, q, hod, team)


@router.get("/reports/attendance/excel")
def report_attendance_excel(start: date | None = None, end: date | None = None, q: str = "", hod: str = "", team: str = "",
                            _: Principal = Depends(require(Perm.VIEW_INSIGHTS)), db: Session = Depends(get_db)) -> Response:
    rep = _attendance(db, start, end, q, hod, team)
    name = f"Field_Sales_Attendance_{rep['from']}_to_{rep['to']}.xlsx"
    return Response(reports.report_excel(rep), media_type=XLSX, headers={"Content-Disposition": f'attachment; filename="{name}"'})


@router.get("/reports/employee/{code}")
def report_employee(code: str, start: date | None = None, end: date | None = None,
                    _: Principal = Depends(require(Perm.VIEW_INSIGHTS)), db: Session = Depends(get_db)) -> dict:
    try:
        return reports.employee_report(db, code, *_range(db, start, end))
    except LookupError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such employee code.") from None
    except reports.ReportError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from None


@router.get("/emails")
def email_log(_: Principal = Depends(require(Perm.VIEW_INSIGHTS)), db: Session = Depends(get_db)) -> list[dict]:
    return reports.email_log(db)


# ---------------------------------------------------------------- automation
class RunDailyIn(BaseModel):
    day: date | None = None
    send: bool = False


@router.get("/jobs")
def job_list(_: Principal = Depends(require(Perm.VIEW_INSIGHTS)), settings: Settings = Depends(get_settings),
             db: Session = Depends(get_db)) -> dict:
    inbox = jobs.inbox_dir(settings)
    waiting = sorted(p.name for p in inbox.iterdir() if p.is_file() and p.suffix.lower() in jobs.FILE_TYPES) if inbox.is_dir() else []
    cfg = get_email(db)
    return {"inbox": str(inbox), "waiting": waiting, "auto_send": cfg.auto_send, "mode": cfg.mode, "runs": jobs.history(db)}


@router.post("/jobs/daily")
def job_daily(body: RunDailyIn, principal: Principal = Depends(require(Perm.UPLOAD_AND_SEND)), settings: Settings = Depends(get_settings),
              engine=Depends(get_engine)) -> dict:
    try:
        return jobs.run_daily(settings, engine, body.day, True if body.send else None, trigger="MANUAL", actor=principal.username)
    except jobs.JobLocked as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from None
    except Exception as exc:
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, f"Daily run failed: {exc}") from None


# ---------------------------------------------------------------- month-end
class MonthIn(BaseModel):
    month: str | None = None


def _month(m: str) -> str:
    try:
        monthly.bounds(m)
    except (ValueError, AttributeError):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Use YYYY-MM.") from None
    return m


def _month_items(db: Session, month: str) -> dict:
    cfg = get_email(db)
    return {"month": month, "label": monthly.label(month), "mode": cfg.mode, "testing": cfg.test_recipient,
            "items": [mail.item_dict(i) for i in monthly.items(db, month)]}


@router.get("/monthly")
def month_list(_: Principal = Depends(require(Perm.VIEW_INSIGHTS)), db: Session = Depends(get_db)) -> dict:
    return {"months": monthly.months(db), "default": monthly.previous_month()}


@router.get("/monthly/{month}")
def month_items(month: str, _: Principal = Depends(require(Perm.VIEW_INSIGHTS)), db: Session = Depends(get_db)) -> dict:
    return _month_items(db, _month(month))


@router.post("/monthly/generate")
def month_generate(body: MonthIn, principal: Principal = Depends(require(Perm.UPLOAD_AND_SEND)), settings: Settings = Depends(get_settings),
                   engine=Depends(get_engine)) -> dict:
    from database.connection import session_scope
    month = _month(body.month or monthly.previous_month())
    try:
        r = monthly.generate(settings, engine, month, trigger="MANUAL", actor=principal.username)
    except jobs.JobLocked as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from None
    if r["status"] == jobs.FAILED:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, r.get("problem") or "Month-end failed.")
    with session_scope(engine) as s:
        return {**_month_items(s, month), "run": r}


@router.post("/monthly/{month}/approve")
def month_approve(month: str, body: ApproveIn, principal: Principal = Depends(require(Perm.UPLOAD_AND_SEND)),
                  settings: Settings = Depends(get_settings), db: Session = Depends(get_db)) -> dict:
    todo = [i for i in monthly.items(db, _month(month)) if i.status in (mail.PENDING, mail.FAILED) and (body.ids is None or i.id in body.ids)]
    done = mail.send_items(db, todo, principal.username, _outbox(settings))
    return {**_month_items(db, month), "sent_now": len(done)}


# ---------------------------------------------------------------- location checks (day map, cases, history)
class CaseIn(BaseModel):
    status: str
    note: str | None = None
    reason: str | None = None


@router.get("/geo/{report_date}")
def geo_summary(report_date: date, _: Principal = Depends(require(Perm.VIEW_INSIGHTS)), db: Session = Depends(get_db)) -> dict:
    return geo.summary(db, report_date)


@router.get("/map/{report_date}/{code}")
def day_map(report_date: date, code: str, principal: Principal = Depends(require(Perm.VIEW_INSIGHTS)), db: Session = Depends(get_db)) -> dict:
    code = bizom.norm_code(code)
    visible = geo.visible_codes(db, principal)
    data = geo.day_map(db, report_date, code) if visible is None or code in visible else None
    if data is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"No Field Sales day for {code} on {report_date:%d-%b-%Y}.")
    return data


@router.get("/cases")
def case_list(start: date | None = None, end: date | None = None, status_: str = Query("", alias="status"), hod: str = "", kind: str = "",
              principal: Principal = Depends(require(Perm.VIEW_INSIGHTS)), db: Session = Depends(get_db)) -> dict:
    d0, d1 = _cases_range(db)
    start, end = start or d0, end or d1
    rows = geo.cases(db, start, end, geo.visible_codes(db, principal), status_, hod, kind)
    return {"from": start.isoformat(), "to": end.isoformat(), "cases": rows, "hods": sorted({r["hod"] for r in rows if r["hod"]}),
            "labels": {k: v[0] for k, v in {**geo.GEO, **photos.PHOTO}.items()}}


@router.put("/cases/{report_date}/{code}")
def case_review(report_date: date, code: str, body: CaseIn, principal: Principal = Depends(require(Perm.VIEW_INSIGHTS)),
                db: Session = Depends(get_db)) -> dict:
    code = bizom.norm_code(code)
    visible = geo.visible_codes(db, principal)
    if visible is not None and code not in visible:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found.")
    try:
        return geo.review(db, code, report_date, body.status, body.note, principal.username, body.reason)
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from None


@router.post("/history")
async def history_import(file: UploadFile = File(...), principal: Principal = Depends(require(Perm.UPLOAD_AND_SEND)),
                         db: Session = Depends(get_db)) -> dict:
    data = await file.read(60 * 1024 * 1024 + 1)
    try:
        return service.import_history(db, file.filename or "history.csv", data)
    except service.UploadError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from None


# ---------------------------------------------------------------- default period for the cases list
def _cases_range(db: Session) -> tuple[date, date]:
    """The last 30 days up to the latest Field Sales day or checked selfie, whichever is later."""
    from datetime import timedelta

    from sqlalchemy import func, select

    from database.models.sales import SalesPhoto
    d0, d1 = reports.default_range(db)
    last = db.scalar(select(func.max(SalesPhoto.day)).where(SalesPhoto.flags.is_not(None)))
    if last and last > d1:
        d1 = last
    return d1 - timedelta(days=30), d1


# ---------------------------------------------------------------- selfie checks
class PhotoRunIn(BaseModel):
    limit: int = 300


@router.get("/photos")
def photos_overview(start: date | None = None, end: date | None = None, sign: str = "",
                    principal: Principal = Depends(require(Perm.VIEW_INSIGHTS)), db: Session = Depends(get_db)) -> dict:
    from datetime import timedelta

    from sqlalchemy import func, select

    from database.models.sales import SalesPhoto
    last = db.scalar(select(func.max(SalesPhoto.day)))
    d1 = end or last or reports.default_range(db)[1]
    return photos.overview(db, start or d1 - timedelta(days=30), d1, geo.visible_codes(db, principal), sign)


@router.post("/photos/run")
def photos_run(body: PhotoRunIn, _: Principal = Depends(require(Perm.UPLOAD_AND_SEND)), engine=Depends(get_engine)) -> dict:
    return photos.fetch(engine, max(1, min(body.limit, 1000)))


# ---------------------------------------------------------------- learning from reviews
@router.get("/learning")
def learning_summary(_: Principal = Depends(require(Perm.VIEW_INSIGHTS)), db: Session = Depends(get_db)) -> dict:
    from sales import learning
    return learning.summary(db)


@router.post("/learning/relearn")
def learning_relearn(_: Principal = Depends(require(Perm.MANAGE_SETTINGS)), db: Session = Depends(get_db)) -> dict:
    from sales import learning, ml
    res = learning.learn(db)
    ml.rerisk(db)
    return res


@router.get("/calibration")
def calibration_sample(n: int = 50, principal: Principal = Depends(require(Perm.VIEW_INSIGHTS)), db: Session = Depends(get_db)) -> dict:
    d0, d1 = _cases_range(db)
    return geo.calibration(db, d0, d1, geo.visible_codes(db, principal), max(10, min(n, 200)))


class SignSwitchIn(BaseModel):
    code: str
    off: bool


@router.post("/learning/switch")
def sign_switch(body: SignSwitchIn, principal: Principal = Depends(require(Perm.MANAGE_SETTINGS)), db: Session = Depends(get_db)) -> dict:
    """Switch a warning sign off (or on again), then recheck the stored days so lists, scores and emails follow."""
    from datetime import timedelta

    from sales import learning, ml, photos
    if body.code not in learning._all_signs():
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Unknown warning sign.")
    rules = get_rules(db)
    off = set(rules.disabled_signs)
    off = off | {body.code} if body.off else off - {body.code}
    save_rules(db, rules.model_copy(update={"disabled_signs": sorted(off)}), principal.username)
    last = reports.default_range(db)[1]
    for i in range(0, 62):                          # recheck the uploaded days of the last two months
        d = last - timedelta(days=i)
        if service.current_upload(db, d):
            geo.check_day(db, d)
    photos.check(db)
    ml.rescore(db)
    return learning.summary(db)


# ---------------------------------------------------------------- holiday calendar (HR confirms; the app never decides)
class HolidayIn(BaseModel):
    kind: str                       # holiday | working | clear
    name: str = ""


@router.get("/holidays")
def holidays(_: Principal = Depends(require(Perm.VIEW_INSIGHTS)), db: Session = Depends(get_db)) -> dict:
    from sales import calendar
    return calendar.state(db)


@router.put("/holidays/{day}")
def holiday_decide(day: date, body: HolidayIn, principal: Principal = Depends(require(Perm.MANAGE_SETTINGS)),
                   db: Session = Depends(get_db)) -> dict:
    from sales import calendar
    try:
        s = calendar.decide(db, day, body.kind, body.name, principal.username)
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from None
    return {**calendar.state(db), "day": {"date": day.isoformat(), "off_day": s.get("off_day") if s else None,
                                          "attendance_pct": s.get("attendance_pct") if s else None, "uploaded": s is not None}}


@router.get("/staff/issues")
def staff_issues(_: Principal = Depends(require(Perm.VIEW_INSIGHTS)), db: Session = Depends(get_db)) -> dict:
    """Staff list problems with proof: possibly left, never in Bizom, joining date looks wrong."""
    from sqlalchemy import select

    from database.models.sales import SalesDayUpload
    from sales import staffcheck
    last = db.scalar(select(SalesDayUpload.report_date).where(SalesDayUpload.is_current.is_(True)).order_by(SalesDayUpload.report_date.desc()))
    if last is None:
        return {"upto": None, "working_days_checked": 0, "possibly_left": [], "never_in_bizom": [], "doj_wrong": []}
    return staffcheck.issues(db, last)



# ---------------------------------------------------------------- holiday state of each person (HR's yearly holiday list)
class StateIn(BaseModel):
    state: str | None = None


@router.get("/staff/states")
def staff_states(_: Principal = Depends(require(Perm.VIEW_INSIGHTS)), db: Session = Depends(get_db)) -> dict:
    from daily import holiday_list
    from sales import holiday_states
    rows = holiday_states.suggestions(db)
    return {"people": rows, "states": holiday_list.STATES,
            "summary": {"people": len(rows), "confirmed": sum(1 for r in rows if r["state"]),
                        "sure": sum(1 for r in rows if not r["state"] and r["suggestion"] and r["suggestion"]["sure"]),
                        "unsure": sum(1 for r in rows if not r["state"] and r["suggestion"] and not r["suggestion"]["sure"]),
                        "no_gps": sum(1 for r in rows if not r["state"] and not r["suggestion"]),
                        "disagree": sum(1 for r in rows if r["state"] and r["suggestion"] and not r["agrees"])}}


@router.post("/staff/states/accept")
def staff_states_accept(principal: Principal = Depends(require(Perm.MANAGE_EMPLOYEES)), db: Session = Depends(get_db)) -> dict:
    """Accept every SURE GPS suggestion for people without a state, then re-apply the holidays of this year."""
    from datetime import date as _date

    from sales import calendar, holiday_states
    n = holiday_states.accept_sure(db, principal.username)
    return {"accepted": n, "field_sales": calendar.apply_year(db, _date.today().year, principal.username)}


@router.put("/staff/{code}/state")
def staff_state(code: str, body: StateIn, principal: Principal = Depends(require(Perm.MANAGE_EMPLOYEES)), db: Session = Depends(get_db)) -> dict:
    from datetime import date as _date

    from sales import calendar, holiday_states
    try:
        holiday_states.set_state(db, code.upper(), body.state, principal.username)
    except LookupError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not on the staff list.") from None
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from None
    return {"code": code.upper(), "state": body.state, "field_sales": calendar.apply_year(db, _date.today().year, principal.username)}
