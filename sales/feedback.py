"""'Was this right?' answers from the Field Sales emails (pilot): each flagged person in a HOD's email gets two signed links.
Opening a link only shows a confirm page (mail scanners open links on their own); the answer is saved when the HOD presses
the button, as a review of that person-day - the same feedback the HR Portal's review screen gives the learning model.
An HR review is never overwritten by an email answer. Links work only when the app has a public address (APP_PUBLIC_URL)."""

from __future__ import annotations

import base64
import hashlib
import hmac
import time
from datetime import date
from urllib.parse import urlparse

from sqlalchemy import select
from sqlalchemy.orm import Session

VALID_DAYS = 21
ANSWERS = {"right": ("ACTION", "REAL_ISSUE", "Right - needs action"), "wrong": ("OK", "OTHER", "Not right - nothing wrong")}


def _key() -> bytes | None:
    from core.config import get_settings
    k = get_settings().api.secret_key
    return k.get_secret_value().encode() if k else None


def public_url() -> str | None:
    """The address HODs can reach, or None (then no links are put in the emails)."""
    from core.config import get_settings
    u = (get_settings().app.public_url or "").rstrip("/")
    host = urlparse(u).hostname or ""
    return u if u.startswith(("http://", "https://")) and host not in ("localhost", "127.0.0.1", "::1") else None


def token(code: str, day: date, who: str, now: float | None = None) -> str | None:
    key = _key()
    if not key:
        return None
    exp = int((now or time.time()) + VALID_DAYS * 86400)
    payload = f"{code}|{day.isoformat()}|{who}|{exp}"
    sig = hmac.new(key, payload.encode(), hashlib.sha256).hexdigest()[:32]
    return base64.urlsafe_b64encode(f"{payload}|{sig}".encode()).decode().rstrip("=")


def read(tok: str, now: float | None = None) -> tuple[str, date, str] | None:
    key = _key()
    if not key:
        return None
    try:
        raw = base64.urlsafe_b64decode(tok + "=" * (-len(tok) % 4)).decode()
        code, d, who, exp, sig = raw.split("|")
    except Exception:
        return None
    good = hmac.new(key, f"{code}|{d}|{who}|{exp}".encode(), hashlib.sha256).hexdigest()[:32]
    if not hmac.compare_digest(good, sig) or int(exp) < (now or time.time()):
        return None
    return code, date.fromisoformat(d), who


def links(checks: list[dict], day: date, who: str, n: int = 5) -> list[dict]:
    base = public_url()
    if not base:
        return []
    out = []
    for c in checks[:n]:
        t = token(c["code"], day, who)
        if t:
            out.append({"name": c["name"], "sign": c["signs"][0]["label"], "right": f"{base}/feedback/sales/{t}/right",
                        "wrong": f"{base}/feedback/sales/{t}/wrong"})
    return out


def record(session: Session, tok: str, answer: str) -> tuple[bool, str]:
    from database.models.sales import SalesCase
    from sales import geo
    got = read(tok)
    if got is None or answer not in ANSWERS:
        return False, "This link is not valid any more (links work for 3 weeks)."
    code, day, who = got
    c = session.scalar(select(SalesCase).where(SalesCase.code == code, SalesCase.day == day))
    if c is not None and c.status != geo.OPEN and not (c.reviewed_by or "").startswith("email:"):
        return False, "HR has already reviewed this day - thank you."
    status, reason, label = ANSWERS[answer]
    geo.review(session, code, day, status, f"Answered from the email by {who}", f"email:{who}"[:100], reason)
    return True, f"Saved: {label}. Thank you - this makes the checks more accurate."
