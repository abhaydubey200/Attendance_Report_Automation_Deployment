"""Phases 9-12: analytics scoping, email distribution, AI summary guards, analyst templates."""

from __future__ import annotations

import json
from datetime import date

import httpx
import pytest
from sqlalchemy import func, select

from ai_engine import analyst, query_guard
from ai_engine.ollama_client import OllamaClient
from ai_engine.summary_generator import generate_run_summary
from core.config import AIConfig, load_attendance_rules
from core.exceptions import AuthorizationError
from database.connection import session_scope
from database.models.attendance import ProcessingRun
from database.models.audit import AIExecutionLog, EmailDeliveryLog
from database.models.reporting import AISummary, ReportRegistry
from email_engine.distribution_manager import DistributionError, distribute
from email_engine.email_client import GraphTransport, Message, TransportError
from orchestration.pipeline import approve_run, start_run
from reporting import analytics
from security.permissions import Principal
from tests.integration.test_ingestion import DAY, define_all, load_day, registry  # noqa: F401

RULES = load_attendance_rules()
HR = Principal(1, "hr", "HR", permissions=frozenset({"ATTENDANCE_VIEW_AGGREGATE", "ATTENDANCE_VIEW_EMPLOYEE",
                                                     "ATTENDANCE_VIEW_ALL_DEPARTMENTS", "RECONCILIATION_VIEW", "AI_USE"}))
HOD_FIN = Principal(2, "hod", "HOD", permissions=frozenset({"ATTENDANCE_VIEW_AGGREGATE", "ATTENDANCE_VIEW_EMPLOYEE", "AI_USE"}),
                    departments=frozenset({"FIN"}))
DIRECTOR = Principal(3, "dir", "Dir", permissions=frozenset({"ATTENDANCE_VIEW_AGGREGATE", "ATTENDANCE_VIEW_ALL_DEPARTMENTS", "AI_USE"}))


@pytest.fixture
def processed(engine, settings, registry):  # noqa: F811
    define_all(engine)
    load_day(engine, settings, registry)
    res = start_run(engine, settings, DAY, "tester")
    return engine, res.run_id


# ------------------------------------------------------------------ Phase 9
def test_summary_is_scoped(processed):
    engine, _ = processed
    with session_scope(engine) as s:
        org = analytics.summary(s, HR, RULES, DAY)
        fin = analytics.summary(s, HOD_FIN, RULES, DAY)
    assert org["kpis"]["eligible_employees"] == 8 and fin["kpis"]["eligible_employees"] == 2
    assert {d["department_code"] for d in fin["departments"]} == {"FIN"}
    assert fin["data_quality"]["unmapped_employees"] is None        # org-wide indicator hidden from HODs
    assert len(org["trend"]) == 1 and org["run"]["rules_approved"] is False


def test_employee_rows_require_permission_and_scope(processed):
    engine, _ = processed
    with session_scope(engine) as s:
        with pytest.raises(AuthorizationError):
            analytics.employee_rows(s, DIRECTOR, DAY)
        rows = analytics.employee_rows(s, HOD_FIN, DAY)
        assert {r["department_code"] for r in rows} == {"FIN"}
        with pytest.raises(LookupError):
            analytics.employee_history(s, HOD_FIN, "TEST-0001", DAY, DAY)   # SALES employee: invisible, not "forbidden"
        hist = analytics.employee_history(s, HR, "TEST-0001", DAY, DAY)
        assert hist["rows"][0]["status"] == "PRESENT"
        with pytest.raises(ValueError):
            analytics.trend(s, HR, RULES, date(2026, 1, 1), DAY)          # range limit


def test_data_quality(processed):
    engine, _ = processed
    with session_scope(engine) as s:
        dq = analytics.data_quality(s, DAY, DAY)
    assert dq["totals"]["source_records"] > 0 and dq["unmapped_employees"] == 4


# ------------------------------------------------------------------ Phase 10
def test_distribution_requires_approval_then_uses_outbox(processed, settings):
    engine, run_id = processed
    with session_scope(engine) as s, pytest.raises(DistributionError, match="approved by HR"):
        distribute(s, settings, run_id, "hr")
    approve_run(engine, run_id, "hr")
    with session_scope(engine) as s, pytest.raises(DistributionError, match="No approved XLSX"):
        distribute(s, settings, run_id, "hr")
    with session_scope(engine) as s:
        for r in s.scalars(select(ReportRegistry).where(ReportRegistry.run_id == run_id)):
            r.status = "APPROVED"
    with session_scope(engine) as s:
        res = distribute(s, settings, run_id, "hr", sleep=lambda _: None)
    assert res.mode == "TEST" and res.sent > 0 and res.failed == 0
    outbox = settings.storage.area("archive") / "outbox"
    emails = list(outbox.glob("*.eml"))
    assert emails and b"[TEST]" in emails[0].read_bytes() and b"[PROVISIONAL]" in emails[0].read_bytes()
    with session_scope(engine) as s:
        assert s.get(ProcessingRun, run_id).state == "COMPLETED"
        assert {e.recipient for e in s.scalars(select(EmailDeliveryLog))} == {"outbox@test.invalid"}   # never real lists


def test_graph_transport_with_mock(monkeypatch):
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        if "token" in request.url.path:
            return httpx.Response(200, json={"access_token": "t"})
        return httpx.Response(503)

    monkeypatch.setenv("GRAPH_TENANT_ID", "x")
    monkeypatch.setenv("GRAPH_CLIENT_ID", "y")
    monkeypatch.setenv("GRAPH_CLIENT_SECRET", "z")
    t = GraphTransport(httpx.Client(transport=httpx.MockTransport(handler)))
    with pytest.raises(TransportError) as err:
        t.send(Message("a@b.co", ["c@d.co"], "s", "b", []))
    assert err.value.transient and calls[-1].endswith("/sendMail")


# ------------------------------------------------------------------ Phase 11
def _ollama(response_json: dict | None, status=200):
    def handler(request):
        if response_json is None:
            raise httpx.ConnectError("down")
        return httpx.Response(status, json={"response": json.dumps(response_json)})
    cfg = AIConfig(enabled=True, endpoint="http://ollama.test", model="test-model", prompt_version="1", max_retries=1)
    return OllamaClient(cfg, httpx.Client(transport=httpx.MockTransport(handler)), sleep=lambda _: None)


def _ai_settings(settings):
    return settings.model_copy(update={
        "features": settings.features.model_copy(update={"ai_enabled": True}),
        "ai": settings.ai.model_copy(update={"enabled": True, "model": "test-model"})})


def test_ai_summary_accepts_grounded_text(processed, settings):
    engine, run_id = processed
    with session_scope(engine) as s:
        ok = generate_run_summary(s, _ai_settings(settings), run_id,
                                  _ollama({"summary": "Of 8 eligible employees, 2 were present; figures are provisional.",
                                           "highlights": ["Sources need reconciliation"]}))
    assert ok
    with session_scope(engine) as s:
        assert s.scalar(select(AISummary).order_by(AISummary.id.desc())).status == "GENERATED"


def test_ai_summary_rejects_invented_numbers_and_survives_outage(processed, settings):
    engine, run_id = processed
    with session_scope(engine) as s:
        assert not generate_run_summary(s, _ai_settings(settings), run_id,
                                        _ollama({"summary": "Attendance was 97.5% across 450 employees."}))
        assert not generate_run_summary(s, _ai_settings(settings), run_id, _ollama(None))
        assert not generate_run_summary(s, settings, run_id)   # disabled
    with session_scope(engine) as s:
        statuses = [l.status for l in s.scalars(select(AIExecutionLog).order_by(AIExecutionLog.id))]
        assert statuses == ["REJECTED", "UNAVAILABLE", "DISABLED"]


def test_pipeline_continues_when_ai_unavailable(engine, settings, registry):  # noqa: F811
    define_all(engine)
    load_day(engine, settings, registry)
    ai = _ai_settings(settings).model_copy(update={"ai": _ai_settings(settings).ai.model_copy(update={"endpoint": "http://127.0.0.1:9"})})
    res = start_run(engine, ai, DAY, "tester")
    assert res.state == "READY_FOR_REVIEW"
    with session_scope(engine) as s:
        assert s.get(ProcessingRun, res.run_id).ai_status == "UNAVAILABLE"


# ------------------------------------------------------------------ Phase 12
@pytest.mark.parametrize("q,intent", [
    ("What was yesterday's overall attendance?", "OVERALL_ATTENDANCE"),
    ("Which department had the highest absenteeism?", "DEPARTMENT_HIGHEST_ABSENT"),
    ("Show employees with missing punches", "MISSING_PUNCHES"),
    ("Compare the last two reporting periods", "COMPARE_PERIODS"),
    ("Which source has the most unresolved attendance conflicts?", "SOURCE_CONFLICTS"),
    ("Explain the department-wise attendance trend", "DEPARTMENT_TREND"),
    ("DROP TABLE users; --", None),
])
def test_question_classification(q, intent):
    assert query_guard.parse(q, date(2026, 11, 14)).intent == intent


def test_question_dates():
    assert query_guard.parse("attendance yesterday", date(2026, 11, 14)).day == DAY
    assert query_guard.parse("attendance on 13-11-2026").day == DAY
    assert query_guard.parse("attendance on 2026-11-13").day == DAY


def test_analyst_answers_with_source_and_scope(processed, settings):
    engine, _ = processed
    with session_scope(engine) as s:
        a = analyst.ask(s, settings, HR, "What was the overall attendance on 13-11-2026?")
        assert "8 eligible" in a["text"] and a["period"] == "2026-11-13" and "provisional" in a["source"]
        fin = analyst.ask(s, settings, HOD_FIN, "overall attendance on 2026-11-13")
        assert "2 eligible" in fin["text"]
        d = analyst.ask(s, settings, DIRECTOR, "show missing punches on 2026-11-13")
        assert "not authorised" in d["text"]
        u = analyst.ask(s, settings, HR, "tell me a joke")
        assert u["intent"] is None and "I can answer" in u["text"]
        with pytest.raises(AuthorizationError):
            analyst.ask(s, settings, Principal(9, "x", "x"), "overall attendance")
    with session_scope(engine) as s:
        assert s.scalar(select(func.count()).select_from(AIExecutionLog).where(AIExecutionLog.feature == "ANALYST")) == 4
