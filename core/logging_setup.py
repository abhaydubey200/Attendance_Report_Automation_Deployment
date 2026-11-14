"""Structured logging with secret redaction (PRD 21.6).

Logs must never contain passwords, tokens or unnecessary personal information.
The redaction filter is a safety net; callers must still avoid logging such data.
"""

from __future__ import annotations

import contextvars
import json
import logging
import re
from logging.handlers import RotatingFileHandler
from typing import Any

from core.timeutils import now_utc

run_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar("run_id", default=None)

_SENSITIVE_KEYS = re.compile(r"(pass(word|wd)?|pwd|secret|token|api[_-]?key|authorization|credential)", re.I)
_INLINE_SECRET = re.compile(
    r"(?i)\b(pass(?:word|wd)?|pwd|secret|token|api[_-]?key)\b(\s*[=:]\s*)([^\s;,&]+)"
)
REDACTED = "***REDACTED***"

_STD_ATTRS = set(vars(logging.makeLogRecord({}))) | {"message", "asctime"}


def redact_text(text: str) -> str:
    return _INLINE_SECRET.sub(lambda m: f"{m.group(1)}{m.group(2)}{REDACTED}", text)


def redact_value(key: str, value: Any) -> Any:
    if _SENSITIVE_KEYS.search(key):
        return REDACTED
    if isinstance(value, dict):
        return {k: redact_value(str(k), v) for k, v in value.items()}
    if isinstance(value, str):
        return redact_text(value)
    return value


class RedactingFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = redact_text(record.getMessage())
        record.args = None
        for key in list(vars(record)):
            if key not in _STD_ATTRS:
                setattr(record, key, redact_value(key, getattr(record, key)))
        return True


class RunContextFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.run_id = run_id_var.get()
        return True


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": now_utc().isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
            "run_id": getattr(record, "run_id", None),
        }
        extras = {k: v for k, v in vars(record).items() if k not in _STD_ATTRS and k != "run_id"}
        if extras:
            payload["extra"] = extras
        if record.exc_info:
            payload["exc"] = redact_text(self.formatException(record.exc_info))
        return json.dumps(payload, default=str, ensure_ascii=False)


_HANDLER_TAG = "_apis_mis_handler"


def configure_logging(settings) -> None:
    """Configure the root logger once. Safe to call repeatedly (e.g. app factory called repeatedly)."""
    root = logging.getLogger()
    if any(getattr(h, _HANDLER_TAG, False) for h in root.handlers):
        return

    cfg = settings.logging
    cfg.dir.mkdir(parents=True, exist_ok=True)
    level = getattr(logging, cfg.level)

    file_handler = RotatingFileHandler(
        cfg.dir / cfg.file_name, maxBytes=cfg.max_bytes, backupCount=cfg.backup_count, encoding="utf-8"
    )
    file_handler.setFormatter(
        JsonFormatter() if cfg.json_format else logging.Formatter("%(asctime)s %(levelname)s %(name)s [%(run_id)s] %(message)s")
    )
    console = logging.StreamHandler()
    console.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))

    for handler in (file_handler, console):
        handler.addFilter(RunContextFilter())
        handler.addFilter(RedactingFilter())
        setattr(handler, _HANDLER_TAG, True)
        root.addHandler(handler)
    root.setLevel(level)
    # Keep third-party noise down.
    for noisy in ("sqlalchemy.engine", "alembic", "urllib3", "watchfiles", "uvicorn.access"):
        logging.getLogger(noisy).setLevel(max(level, logging.WARNING))
