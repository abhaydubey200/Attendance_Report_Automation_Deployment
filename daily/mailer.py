"""Sending: test mode saves each email as a .eml file in the outbox (nothing leaves the
machine); live mode sends through SMTP (e.g. Microsoft 365 smtp.office365.com:587).
The SMTP password comes only from the environment variable SMTP_PASSWORD."""

from __future__ import annotations

import os
import smtplib
from dataclasses import dataclass
from email.message import EmailMessage
from email.utils import formatdate, make_msgid
from pathlib import Path

from core.config import EmailSettings
from core.timeutils import now_utc


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


def build_message(sender: str, to: list[str], subject: str, html: str, text: str, attachments: list[Attachment]) -> EmailMessage:
    msg = EmailMessage()
    msg["From"], msg["To"], msg["Subject"] = sender, ", ".join(to), subject
    msg["Date"], msg["Message-ID"] = formatdate(localtime=True), make_msgid(domain="apis-attendance.local")
    msg.set_content(text)
    msg.add_alternative(html, subtype="html")
    for a in attachments:
        maintype, subtype = a.mime.split("/", 1)
        msg.add_attachment(a.content, maintype=maintype, subtype=subtype, filename=a.filename)
    return msg


def send(cfg: EmailSettings, message: EmailMessage, outbox: Path) -> SendResult:
    if cfg.mode == "test":
        outbox.mkdir(parents=True, exist_ok=True)
        path = outbox / f"{now_utc():%Y%m%dT%H%M%S%f}.eml"
        path.write_bytes(bytes(message))
        return SendResult("SAVED", str(path))
    if not (cfg.smtp_host and cfg.sender):
        raise MailError("Live email needs an SMTP server and a sender address (Settings -> Email).")
    password = os.environ.get("SMTP_PASSWORD")
    try:
        with smtplib.SMTP(cfg.smtp_host, cfg.smtp_port, timeout=30) as smtp:
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
    return SendResult("SENT")
