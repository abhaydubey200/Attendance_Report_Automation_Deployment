"""Daily emails: routing check, today's planned emails, preview, approve & send, resend, attachments."""

from __future__ import annotations

from collections import Counter
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import HTMLResponse, Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

from api.deps import get_db, get_settings, require
from core.config import Settings
from daily import mail, routing, service
from daily.settings_store import get_email_settings
from database.models.daily import MailItem
from security.permissions import Perm, Principal

router = APIRouter(tags=["mail"])
PREVIEW_CSP = "default-src 'none'; style-src 'unsafe-inline'; img-src data:; sandbox; frame-ancestors 'self'"
DASHBOARD_CSP = "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src data:; sandbox allow-scripts"


@router.get("/routing")
def routing_overview(_: Principal = Depends(require(Perm.VIEW_INSIGHTS)), settings: Settings = Depends(get_settings),
                     db: Session = Depends(get_db)) -> dict:
    return routing.overview(db, get_email_settings(db, settings))


class RecipientIn(BaseModel):
    email: str
    active: bool | None = None
    name: str | None = None


@router.put("/routing/recipients")
def set_recipient(body: RecipientIn, principal: Principal = Depends(require(Perm.MANAGE_SETTINGS)),
                  db: Session = Depends(get_db)) -> dict:
    try:
        rec = routing.set_recipient(db, body.email, body.active, body.name, principal.username)
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from None
    return {"email": rec.email, "active": rec.active, "name": rec.name}


def _day_items(db: Session, settings: Settings, day: date) -> dict:
    items = mail.items_for(db, day)
    cfg = get_email_settings(db, settings)
    return {"report_date": day.isoformat(), "mode": cfg.mode, "approval_required": cfg.approval_required,
            "provider": cfg.provider, "items": [mail.item_dict(i) for i in items],
            "status": dict(Counter(i.status for i in items)), "planned": bool(items)}


@router.get("/days/{report_date}/mail")
def day_mail(report_date: date, _: Principal = Depends(require(Perm.VIEW_INSIGHTS)), settings: Settings = Depends(get_settings),
             db: Session = Depends(get_db)) -> dict:
    return _day_items(db, settings, report_date)


@router.post("/days/{report_date}/mail/plan")
def replan(report_date: date, principal: Principal = Depends(require(Perm.UPLOAD_AND_SEND)),
           settings: Settings = Depends(get_settings), db: Session = Depends(get_db)) -> dict:
    """Prepare the emails again (e.g. after fixing routing on the Employees screen). Already-sent recipients stay sent."""
    up = service.current_upload(db, report_date)
    if up is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No upload for that date.")
    mail.build_plan(db, settings, up, principal.username)
    return _day_items(db, settings, report_date)


class ApproveIn(BaseModel):
    ids: list[int] | None = None


@router.post("/days/{report_date}/mail/approve")
def approve(report_date: date, body: ApproveIn, principal: Principal = Depends(require(Perm.UPLOAD_AND_SEND)),
            settings: Settings = Depends(get_settings), db: Session = Depends(get_db)) -> dict:
    done = mail.approve(db, settings, report_date, principal.username, body.ids)
    return {**_day_items(db, settings, report_date), "sent_now": len(done)}


def _item(db: Session, item_id: int) -> MailItem:
    item = db.get(MailItem, item_id)
    if item is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such email.")
    return item


@router.post("/mail/{item_id}/resend")
def resend(item_id: int, principal: Principal = Depends(require(Perm.MANAGE_SETTINGS)), settings: Settings = Depends(get_settings),
           db: Session = Depends(get_db)) -> dict:
    """Explicit resend by an administrator: overrides the once-per-day duplicate guard for this recipient."""
    item = _item(db, item_id)
    if item.status in (mail.HELD, mail.DISABLED, mail.SUPERSEDED):
        raise HTTPException(status.HTTP_409_CONFLICT, f"This email is {item.status.lower()}: {item.note or ''}".strip())
    mail.send_items(db, settings, [item], principal.username, force=True)
    return mail.item_dict(item)


@router.get("/mail/{item_id}/preview", response_class=HTMLResponse)
def preview(item_id: int, _: Principal = Depends(require(Perm.VIEW_INSIGHTS)), settings: Settings = Depends(get_settings),
            db: Session = Depends(get_db)) -> HTMLResponse:
    html, _, _ = mail.render(db, settings, _item(db, item_id))
    return HTMLResponse(html, headers={"Content-Security-Policy": PREVIEW_CSP})


@router.get("/mail/{item_id}/attachment/{kind}")
def attachment(item_id: int, kind: str, _: Principal = Depends(require(Perm.VIEW_INSIGHTS)),
               settings: Settings = Depends(get_settings), db: Session = Depends(get_db)) -> Response:
    _, _, files = mail.render(db, settings, _item(db, item_id))
    suffix = {"excel": ".xlsx", "dashboard": ".html"}.get(kind)
    wanted = [f for f in files if suffix and f.filename.endswith(suffix)]
    if not wanted:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "This email has no such attachment.")
    f = wanted[0]
    headers = {"Content-Disposition": f'attachment; filename="{f.filename}"'}
    if kind == "dashboard":
        headers["Content-Security-Policy"] = DASHBOARD_CSP
    return Response(f.content, media_type=f.mime, headers=headers)
