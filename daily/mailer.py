"""Delivery. Test mode saves each email as a .eml file in the outbox (nothing leaves the machine).
Live mode uses the provider chosen in Settings (adapter pattern):

* smtp  - any SMTP server (e.g. Microsoft 365 smtp.office365.com:587). Password: env SMTP_PASSWORD.
* graph - Microsoft Graph sendMail as the sender mailbox (app registration with Mail.Send).
          Env GRAPH_TENANT_ID, GRAPH_CLIENT_ID, GRAPH_CLIENT_SECRET.
* gmail - Gmail API users.messages.send. Env GMAIL_CLIENT_ID, GMAIL_CLIENT_SECRET, GMAIL_REFRESH_TOKEN.

Secrets are only ever read from the environment, never stored in the app or database.
"""

from __future__ import annotations

import base64
import os
import smtplib
from dataclasses import dataclass
from email.message import EmailMessage
from email.utils import formatdate, make_msgid
from pathlib import Path

import httpx

from core.config import EmailSettings
from core.timeutils import now_utc

TIMEOUT = 30


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
    for a in attachments:
        maintype, subtype = a.mime.split("/", 1)
        msg.add_attachment(a.content, maintype=maintype, subtype=subtype, filename=a.filename)
    return msg


# ---------------------------------------------------------------------------- providers
def _env(*names: str) -> list[str]:
    values = [os.environ.get(n, "") for n in names]
    missing = [n for n, v in zip(names, values) if not v]
    if missing:
        raise MailError(f"Missing environment variable(s): {', '.join(missing)}.")
    return values


def _smtp(cfg: EmailSettings, message: EmailMessage) -> None:
    if not cfg.smtp_host:
        raise MailError("SMTP needs the server name (Settings -> Email).")
    password = os.environ.get("SMTP_PASSWORD")
    try:
        with smtplib.SMTP(cfg.smtp_host, cfg.smtp_port, timeout=TIMEOUT) as smtp:
            if cfg.smtp_starttls:
                smtp.starttls()
            if cfg.smtp_username:
                if not password:
                    raise MailError("SMTP_PASSWORD is not set in the environment.")
                smtp.login(cfg.smtp_username, password)
            smtp.send_message(message)
    except smtplib.SMTPAuthenticationError as exc:
        raise MailError("The SMTP server rejected the username/password.") from exc
    except (smtplib.SMTPException, OSError) as exc:
        raise MailError(f"Could not send: {type(exc).__name__}: {exc}"[:300]) from exc


def _http(method: str, url: str, **kw) -> httpx.Response:
    try:
        r = httpx.request(method, url, timeout=TIMEOUT, **kw)
    except httpx.HTTPError as exc:
        raise MailError(f"Could not reach the mail service: {type(exc).__name__}") from exc
    if r.status_code >= 400:
        raise MailError(f"Mail service answered {r.status_code}: {r.text[:200]}")
    return r


def _graph(cfg: EmailSettings, message: EmailMessage) -> None:
    tenant, client_id, secret = _env("GRAPH_TENANT_ID", "GRAPH_CLIENT_ID", "GRAPH_CLIENT_SECRET")
    token = _http("POST", f"https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token",
                  data={"grant_type": "client_credentials", "client_id": client_id, "client_secret": secret,
                        "scope": "https://graph.microsoft.com/.default"}).json()["access_token"]
    # sendMail accepts the whole MIME message, base64-encoded, as text/plain.
    _http("POST", f"https://graph.microsoft.com/v1.0/users/{cfg.sender}/sendMail",
          headers={"Authorization": f"Bearer {token}", "Content-Type": "text/plain"},
          content=base64.b64encode(bytes(message)))


def _gmail(cfg: EmailSettings, message: EmailMessage) -> None:
    client_id, secret, refresh = _env("GMAIL_CLIENT_ID", "GMAIL_CLIENT_SECRET", "GMAIL_REFRESH_TOKEN")
    token = _http("POST", "https://oauth2.googleapis.com/token",
                  data={"grant_type": "refresh_token", "client_id": client_id, "client_secret": secret,
                        "refresh_token": refresh}).json()["access_token"]
    _http("POST", "https://gmail.googleapis.com/gmail/v1/users/me/messages/send",
          headers={"Authorization": f"Bearer {token}"},
          json={"raw": base64.urlsafe_b64encode(bytes(message)).decode()})


PROVIDERS = {"smtp": _smtp, "graph": _graph, "gmail": _gmail}


def send(cfg: EmailSettings, message: EmailMessage, outbox: Path) -> SendResult:
    if cfg.mode == "test":
        outbox.mkdir(parents=True, exist_ok=True)
        path = outbox / f"{now_utc():%Y%m%dT%H%M%S%f}.eml"
        path.write_bytes(bytes(message))
        return SendResult("SAVED", str(path))
    if not cfg.sender:
        raise MailError("Live email needs the sender mailbox (Settings -> Email).")
    PROVIDERS[cfg.provider](cfg, message)
    return SendResult("SENT")
