from __future__ import annotations

import json
import logging

from core.logging_setup import REDACTED, JsonFormatter, RedactingFilter, RunContextFilter, redact_text, run_id_var


def _record(msg, **extra):
    record = logging.makeLogRecord({"name": "t", "levelno": logging.INFO, "levelname": "INFO", "msg": msg})
    for k, v in extra.items():
        setattr(record, k, v)
    return record


def test_inline_secrets_are_redacted():
    out = redact_text("connect password=Sup3r;token: abc123 user=bob")
    assert "Sup3r" not in out and "abc123" not in out
    assert "user=bob" in out


def test_sensitive_extra_fields_are_redacted():
    record = _record("login attempt", password="hunter2", db_password="x", username="alice")
    RedactingFilter().filter(record)
    assert record.password == REDACTED and record.db_password == REDACTED
    assert record.username == "alice"


def test_json_formatter_includes_run_id_and_extras():
    token = run_id_var.set("RUN-1")
    try:
        record = _record("stage done", stage="validation", api_key="k")
        RunContextFilter().filter(record)
        RedactingFilter().filter(record)
        payload = json.loads(JsonFormatter().format(record))
    finally:
        run_id_var.reset(token)
    assert payload["run_id"] == "RUN-1"
    assert payload["extra"]["stage"] == "validation"
    assert payload["extra"]["api_key"] == REDACTED


def test_configure_logging_writes_file(settings):
    from core.logging_setup import configure_logging

    root = logging.getLogger()
    before = list(root.handlers)
    try:
        configure_logging(settings)
        configure_logging(settings)  # idempotent
        added = [h for h in root.handlers if h not in before]
        assert len(added) == 2
        logging.getLogger("t").warning("hello password=abc")
        for h in added:
            h.flush()
        text = (settings.logging.dir / settings.logging.file_name).read_text(encoding="utf-8")
        assert "hello" in text and "abc" not in text
    finally:
        for h in [h for h in root.handlers if h not in before]:
            root.removeHandler(h)
            h.close()
