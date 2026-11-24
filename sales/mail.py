"""Field Sales daily emails: plan one per recipient, build (email + Excel + dashboard), approve, send.

Uses the shared Gmail sender (daily.mailer) and the shared sender mailbox; everything else (mode, recipients, log) is
Module 2's own. Mode "test" saves every email to the outbox instead of sending it.
"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from core.timeutils import now_utc
from daily.mailer import Attachment, MailError, build_message, send
from database.models.sales import SalesDayUpload, SalesEmployee, SalesEmployeeDay, SalesMailItem
from sales.util import utc_iso
from sales import report, routing
from sales.config import get_email

PENDING, HELD, SENT, SAVED, TEST_SENT, FAILED, DUPLICATE, SUPERSEDED = (
    "PENDING", "HELD", "SENT", "SAVED", "TEST_SENT", "FAILED", "DUPLICATE", "SUPERSEDED")
REPLACEABLE = (PENDING, HELD, FAILED, DUPLICATE)
DELIVERED = (SENT, SAVED, TEST_SENT)
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def items_for(session: Session, day: date) -> list[SalesMailItem]:
    return list(session.scalars(select(SalesMailItem).where(SalesMailItem.report_date == day, SalesMailItem.status != SUPERSEDED,
                                                          SalesMailItem.recipient_key.not_like("MONTHLY:%")).order_by(SalesMailItem.id)))


def plan(session: Session, up: SalesDayUpload) -> list[SalesMailItem]:
    cfg = get_email(session)
    staff = {e.code: e for e in session.scalars(select(SalesEmployee))}
    rows = list(session.scalars(select(SalesEmployeeDay).where(SalesEmployeeDay.upload_id == up.upload_id)))
    by_code = {r.code: r for r in rows}
    delivered = {k for (k,) in session.execute(select(SalesMailItem.recipient_key).where(
        SalesMailItem.report_date == up.report_date, SalesMailItem.status.in_(DELIVERED)))}
    day_summary = json.loads(up.summary or "{}")
    hold = None
    if (day_summary.get("verify") or {}).get("mismatch_count"):
        v = day_summary["verify"]
        hold = (f"Held by the self-check: {v['mismatch_count']} difference(s) between the stored day and Bizom's file "
                f"(e.g. {v['mismatches'][0]}). Upload the day again or tell HR.")
    elif day_summary.get("off_day_unconfirmed"):
        hold = (f"Held: {up.report_date:%d-%b-%Y} looks like a holiday ({day_summary['off_day']}). Confirm it as a holiday or a "
                f"working day in Field Sales > Holidays; the emails are prepared again after that.")
    items = []
    for rec in routing.recipients(set(by_code), staff, cfg):
        scope = [by_code[c] for c in rec.codes if c in by_code]
        if not scope:
            continue
        status, note = rec.status, rec.note
        if hold:
            status, note = HELD, hold
        elif status == HELD and cfg.test_recipient:
            status, note = PENDING, f"Testing: {rec.note}"
        if status == PENDING and rec.key in delivered:
            status, note = DUPLICATE, "Already sent for this day."
        cnt = Counter(r.status for r in scope)
        flagged = sum(1 for r in scope if r.flags)
        subject = (f"Field Sales Attendance | {up.report_date:%d-%b-%Y} | {rec.name}"
                   + (f" | {cnt['ABSENT']} absent" if cnt["ABSENT"] else "") + (f" · {flagged} to check" if flagged else ""))
        item = SalesMailItem(upload_id=up.upload_id, report_date=up.report_date, recipient_key=rec.key[:200], recipient_name=rec.name[:200],
                             role=rec.role, to_addrs=", ".join(rec.to) or None, subject=subject[:300],
                             content=json.dumps({"codes": sorted(rec.codes), "view": rec.view}),
                             counts=json.dumps({"people": len(scope), "absent": cnt["ABSENT"], "late": cnt["LATE"], "flagged": flagged,
                                                "attendance_pct": report.pct_of(scope)}),
                             status=status, note=note, attempts=0)
        session.add(item)
        items.append(item)
    session.flush()
    return items


def render(session: Session, item: SalesMailItem) -> tuple[str, str, list[Attachment]]:
    c = json.loads(item.content)
    if c.get("kind") == "monthly":
        from sales import monthly
        return monthly.render(session, item)
    up = session.get(SalesDayUpload, item.upload_id)
    c = json.loads(item.content)
    codes = set(c["codes"])
    rows = [r for r in session.scalars(select(SalesEmployeeDay).where(SalesEmployeeDay.upload_id == up.upload_id)) if r.code in codes]
    cfg = get_email(session)
    from sales import checks
    found = checks.day_checks(session, up.report_date, codes)
    from sales import learning, trust
    if item.role not in trust.FULL_ROLES:
        found = trust.for_email(found, learning.state(session))      # unproven judgment signs: HR only
    proof = checks.proof(session, up.report_date, found) if item.role in checks.PROOF_ROLES else None
    ctx = checks.context(session, up.report_date, codes)
    if c["view"] == "hr":
        from sales import staffcheck
        ctx["staff_issues"] = staffcheck.issues(session, up.report_date)
    view = report.build_view(rows, json.loads(up.summary), c["view"], item.recipient_name, up.report_date, found, proof, ctx)
    if item.role != "HR":
        from sales import feedback
        view["feedback"] = feedback.links(found, up.report_date, item.recipient_key)
    files = []
    if cfg.attach_excel:
        files.append(Attachment(f"{view['stem']}.xlsx", report.excel(view), XLSX))
    if cfg.attach_dashboard:
        files.append(Attachment(f"{view['stem']}_dashboard.html", report.dashboard(view), "text/html"))
    return report.email_html(view), report.email_text(view), files


@dataclass
class _Cfg:                      # what daily.mailer.send needs
    mode: str
    sender: str | None


def _sender(session: Session) -> str | None:
    from core.config import get_settings
    from daily.settings_store import get_email_settings
    return get_email_settings(session, get_settings()).sender          # the shared sender mailbox (read only)


def send_items(session: Session, items: list[SalesMailItem], actor: str, outbox, force: bool = False) -> list[SalesMailItem]:
    cfg = get_email(session)
    sender = _sender(session) or "attendance@localhost"
    done = []
    for item in items:
        ok = item.status in (PENDING, FAILED) or (force and item.status in (DUPLICATE,) + DELIVERED)
        if not ok:
            continue
        to = [a.strip() for a in (item.to_addrs or "").split(",") if a.strip()]
        testing = cfg.test_recipient
        if not to and not testing:
            item.status, item.note = HELD, item.note or "No address."
            continue
        pilot = (cfg.mode == "test" and not testing and to and all(a.lower() in {p.lower() for p in cfg.pilot_live} for a in to))
        html, text, attachments = render(session, item)
        subject, cc = item.subject, []
        if testing:      # only the testers receive it (really sent, whatever the mode); the real recipients are named in the banner
            from daily.mail import _with_banner

            would = ", ".join(to) or "(address not set yet)"
            html = _with_banner(html.replace("<body", f"<body data-test-for=\"{would}\"", 1), would)
            text = f"*** TEST EMAIL - in live use this goes to {would} ***\n\n" + text
            subject, to = f"[TEST] {subject}", [testing]
            cc = [a for a in cfg.test_cc if a.lower() != testing.lower()]
        bcc = [] if testing else [a for a in cfg.always_bcc if a not in to]
        msg = build_message(sender, to, subject, html, text, attachments, cc=cc, bcc=bcc)
        item.attempts += 1
        try:
            res = send(_Cfg("live" if (pilot or testing) else cfg.mode, sender), msg, outbox / item.report_date.isoformat())
            item.status = TEST_SENT if testing else res.status
            item.outbox_file, item.sent_at, item.approved_by = res.outbox_file, now_utc(), actor
            who = testing + (f" (CC {', '.join(cc)})" if cc else "") if testing else ""
            item.note = (f"Test only: {'delivered to' if res.status == 'SENT' else 'saved to the outbox for'} {who}. The real recipient has not received it."
                         if testing else "Pilot: really sent (test mode for everyone else)." if pilot else
                         ("Saved to the outbox (test mode - not sent)." if res.status == SAVED else None))
        except MailError as exc:
            item.status, item.note = FAILED, str(exc)[:500]
        done.append(item)
    session.flush()
    return done


def item_dict(i: SalesMailItem) -> dict:
    return {"id": i.id, "report_date": i.report_date.isoformat(), "key": i.recipient_key, "name": i.recipient_name, "role": i.role,
            "to": i.to_addrs or "", "subject": i.subject, "status": i.status, "note": i.note, "attempts": i.attempts,
            "counts": json.loads(i.counts or "{}"), "sendable": i.status in (PENDING, FAILED),
            "sent_at": utc_iso(i.sent_at), "approved_by": i.approved_by}
