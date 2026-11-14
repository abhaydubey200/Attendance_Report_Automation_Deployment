"""Mail transports (PRD 13.2). Credentials only from environment variables.

* OutboxTransport -- writes RFC 822 .eml files (test mode; nothing leaves the machine)
* SmtpTransport   -- approved SMTP relay
* GraphTransport  -- Microsoft Graph sendMail with an app registration (client credentials)
Real transports are refused by configuration validation outside production.
"""

from __future__ import annotations

import base64
import os
import smtplib
from dataclasses import dataclass
from email.message import EmailMessage
from pathlib import Path

import httpx

from core.config import Settings
from core.timeutils import now_utc


class TransportError(Exception):
    """Delivery failed. `transient` tells the caller whether a retry may help."""

    def __init__(self, message: str, transient: bool = True) -> None:
        super().__init__(message)
        self.transient = transient


@dataclass
class Attachment:
    filename: str
    content: bytes
    mime: str = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


@dataclass
class Message:
    sender: str
    to: list[str]
    subject: str
    body: str
    attachments: list[Attachment]

    def to_mime(self) -> EmailMessage:
        msg = EmailMessage()
        msg["From"], msg["To"], msg["Subject"] = self.sender, ", ".join(self.to), self.subject
        msg.set_content(self.body)
        for a in self.attachments:
            maintype, subtype = a.mime.split("/", 1)
            msg.add_attachment(a.content, maintype=maintype, subtype=subtype, filename=a.filename)
        return msg


class OutboxTransport:
    mode = "TEST"

    def __init__(self, folder: Path) -> None:
        self.folder = folder
        folder.mkdir(parents=True, exist_ok=True)

    def send(self, message: Message) -> str:
        name = f"{now_utc():%Y%m%dT%H%M%S%f}_{abs(hash(tuple(message.to))) % 10**8}.eml"
        (self.folder / name).write_bytes(bytes(message.to_mime()))
        return name


class SmtpTransport:
    mode = "LIVE"

    def __init__(self, host: str, port: int, starttls: bool) -> None:
        self.host, self.port, self.starttls = host, port, starttls

    def send(self, message: Message) -> str:
        user, password = os.environ.get("SMTP_USER"), os.environ.get("SMTP_PASSWORD")
        try:
            with smtplib.SMTP(self.host, self.port, timeout=30) as smtp:
                if self.starttls:
                    smtp.starttls()
                if user and password:
                    smtp.login(user, password)
                smtp.send_message(message.to_mime())
        except smtplib.SMTPRecipientsRefused as exc:
            raise TransportError(f"recipient refused: {list(exc.recipients)}", transient=False) from exc
        except (smtplib.SMTPException, OSError) as exc:
            raise TransportError(type(exc).__name__) from exc
        return "smtp"


class GraphTransport:
    mode = "LIVE"
    TOKEN_URL = "https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token"
    SEND_URL = "https://graph.microsoft.com/v1.0/users/{sender}/sendMail"

    def __init__(self, client: httpx.Client | None = None) -> None:
        self.client = client or httpx.Client(timeout=30)

    def _token(self) -> str:
        tenant, cid, secret = (os.environ.get(k) for k in ("GRAPH_TENANT_ID", "GRAPH_CLIENT_ID", "GRAPH_CLIENT_SECRET"))
        if not (tenant and cid and secret):
            raise TransportError("Microsoft Graph credentials are not configured", transient=False)
        r = self.client.post(self.TOKEN_URL.format(tenant=tenant), data={
            "client_id": cid, "client_secret": secret, "grant_type": "client_credentials",
            "scope": "https://graph.microsoft.com/.default"})
        if r.status_code != 200:
            raise TransportError(f"token request failed ({r.status_code})", transient=r.status_code >= 500)
        return r.json()["access_token"]

    def send(self, message: Message) -> str:
        payload = {"message": {
            "subject": message.subject, "body": {"contentType": "Text", "content": message.body},
            "toRecipients": [{"emailAddress": {"address": a}} for a in message.to],
            "attachments": [{"@odata.type": "#microsoft.graph.fileAttachment", "name": a.filename,
                             "contentBytes": base64.b64encode(a.content).decode()} for a in message.attachments],
        }, "saveToSentItems": True}
        r = self.client.post(self.SEND_URL.format(sender=message.sender), json=payload,
                             headers={"Authorization": f"Bearer {self._token()}"})
        if r.status_code not in (200, 202):
            raise TransportError(f"sendMail failed ({r.status_code})", transient=r.status_code in (429, 500, 502, 503, 504))
        return "graph"


def build_transport(settings: Settings):
    cfg = settings.email
    if cfg.transport == "outbox":
        return OutboxTransport(settings.storage.area("archive") / "outbox")
    if cfg.transport == "smtp":
        if not cfg.smtp_host:
            raise TransportError("email.smtp_host is not configured", transient=False)
        return SmtpTransport(cfg.smtp_host, cfg.smtp_port, cfg.smtp_starttls)
    return GraphTransport()
