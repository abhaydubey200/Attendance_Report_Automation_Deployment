"""Delivery through the Gmail API - the only way this application sends email.

* live: Gmail API users.messages.send as the sender mailbox. Secrets only in the environment (.env):
  GMAIL_CLIENT_ID, GMAIL_CLIENT_SECRET and GMAIL_REFRESH_TOKEN (written by ``main.py gmail-auth``).
* test: nothing leaves the machine; each email is saved as a .eml file in the outbox.
"""

from __future__ import annotations

import base64
import os
from dataclasses import dataclass
from email.message import EmailMessage
from email.utils import formatdate, make_msgid
from pathlib import Path

import httpx

from core.config import EmailSettings
from core.timeutils import now_utc
from daily.branding import LOGO_CID, LOGO_SRC, logo_png

TIMEOUT = 30
GMAIL_SECRETS = ("GMAIL_CLIENT_ID", "GMAIL_CLIENT_SECRET", "GMAIL_REFRESH_TOKEN")


class MailError(Exception):
    pass


@dataclass
class Attachment:
    filename: str
    content: bytes
    mime: str


@dataclass
class SendResult:
    status: str               # SENT | SAVED
    outbox_file: str | None = None


def build_message(sender: str, to: list[str], subject: str, html: str, text: str, attachments: list[Attachment],
                  cc: list[str] | None = None, reply_to: str | None = None) -> EmailMessage:
    msg = EmailMessage()
    msg["From"], msg["To"], msg["Subject"] = sender, ", ".join(to), subject
    if cc:
        msg["Cc"] = ", ".join(cc)
    if reply_to:
        msg["Reply-To"] = reply_to
    msg["Date"], msg["Message-ID"] = formatdate(localtime=True), make_msgid(domain="apis-attendance.local")
    msg.set_content(text)
    msg.add_alternative(html, subtype="html")
    if LOGO_SRC in html:                     # embed the logo (multipart/related) so it shows without "load images"
        msg.get_payload()[1].add_related(logo_png(), maintype="image", subtype="png", cid=f"<{LOGO_CID}>",
                                         filename="apis-logo.png", disposition="inline")
    for a in attachments:
        maintype, subtype = a.mime.split("/", 1)
        msg.add_attachment(a.content, maintype=maintype, subtype=subtype, filename=a.filename)
    return msg


def missing_secrets() -> list[str]:
    return [n for n in GMAIL_SECRETS if not os.environ.get(n)]


def _http(method: str, url: str, **kw) -> httpx.Response:
    try:
        r = httpx.request(method, url, timeout=TIMEOUT, **kw)
    except httpx.HTTPError as exc:
        raise MailError(f"Could not reach Gmail: {type(exc).__name__}") from exc
    if r.status_code >= 400:
        raise MailError(f"Gmail answered {r.status_code}: {r.text[:200]}")
    return r


def _gmail(message: EmailMessage) -> None:
    missing = missing_secrets()
    if missing:
        raise MailError(f"Missing environment variable(s): {', '.join(missing)} (run main.py gmail-auth).")
    token = _http("POST", "https://oauth2.googleapis.com/token",
                  data={"grant_type": "refresh_token", "client_id": os.environ["GMAIL_CLIENT_ID"],
                        "client_secret": os.environ["GMAIL_CLIENT_SECRET"],
                        "refresh_token": os.environ["GMAIL_REFRESH_TOKEN"]}).json()["access_token"]
    _http("POST", "https://gmail.googleapis.com/gmail/v1/users/me/messages/send",
          headers={"Authorization": f"Bearer {token}"},
          json={"raw": base64.urlsafe_b64encode(bytes(message)).decode()})


def send(cfg: EmailSettings, message: EmailMessage, outbox: Path) -> SendResult:
    if cfg.mode == "test":
        outbox.mkdir(parents=True, exist_ok=True)
        path = outbox / f"{now_utc():%Y%m%dT%H%M%S%f}.eml"
        path.write_bytes(bytes(message))
        return SendResult("SAVED", str(path))
    if not cfg.sender:
        raise MailError("Live email needs the sender mailbox (Settings -> Email).")
    _gmail(message)
    return SendResult("SENT")
