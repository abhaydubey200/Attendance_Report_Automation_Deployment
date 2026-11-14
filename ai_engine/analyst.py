"""Attendance analyst (PRD 15): authorised natural-language questions answered from
approved, read-only query templates. The answer always states its reporting period
and source run. The language model (optional) may only re-phrase the deterministic
answer; if it is off or its wording adds numbers, the deterministic text is used."""

from __future__ import annotations

import json
import time
from collections import Counter
from datetime import date, timedelta

from sqlalchemy.orm import Session

from ai_engine.context_builder import numbers_in
from ai_engine.ollama_client import AIUnavailable, OllamaClient
from ai_engine.query_guard import INTENTS, parse
from ai_engine.summary_generator import unsupported_numbers
from core.config import Settings, load_attendance_rules
from core.exceptions import AuthorizationError
from database.models.audit import AIExecutionLog
from reporting import analytics
from security.authorization import has_permission
from security.permissions import Perm, Principal

RESULT_LIMIT = 50


def _pct(v) -> str:
    return "pending HR approval" if v is None else f"{v}%"


def _answer(session: Session, principal: Principal, settings: Settings, intent: str, day: date | None) -> dict:
    rules = load_attendance_rules(settings.config_dir)
    run = analytics.current_run(session, day)
    if run is None:
        return {"text": f"No processed data for {day.isoformat() if day else 'any date'} yet.", "table": None, "run": None}
    info = analytics.run_info(run)
    d = run.reporting_date

    if intent == "OVERALL_ATTENDANCE":
        s = analytics.summary(session, principal, rules, d)["kpis"]
        c = s["counts"]
        text = (f"On {d:%d-%b-%Y}: {s['eligible_employees']} eligible employees in your scope; {c['PRESENT']} present, "
                f"{c['ABSENT']} absent, {c['APPROVED_LEAVE']} on approved leave, {c['WORK_FROM_HOME']} WFH, "
                f"{c['UNRESOLVED']} unresolved. Attendance %: {_pct(s['attendance_pct'])}.")
        return {"text": text, "table": None, "run": info}

    if intent == "DEPARTMENT_HIGHEST_ABSENT":
        depts = analytics.summary(session, principal, rules, d)["departments"]
        if not depts:
            return {"text": "No department data in your scope.", "table": None, "run": info}
        top = max(depts, key=lambda x: (x["counts"]["ABSENT"], x["department_code"]))
        table = [[x["department_code"], x["counts"]["ABSENT"], x["eligible"], _pct(x["absenteeism_pct"])]
                 for x in sorted(depts, key=lambda x: -x["counts"]["ABSENT"])]
        text = (f"On {d:%d-%b-%Y}, {top['department_code']} recorded the most absences ({top['counts']['ABSENT']} of "
                f"{top['eligible']}). Absenteeism %: {_pct(top['absenteeism_pct'])}.")
        return {"text": text, "table": {"header": ["Department", "Absent", "Eligible", "Absenteeism %"], "rows": table}, "run": info}

    if intent == "MISSING_PUNCHES":
        if not has_permission(principal, Perm.ATTENDANCE_VIEW_EMPLOYEE):
            return {"text": "You are not authorised to see employee-level records.", "table": None, "run": info}
        rows = analytics.employee_rows(session, principal, d, {"MISSING_PUNCH"})[:RESULT_LIMIT]
        text = f"{len(rows)} employee(s) in your scope had a missing punch on {d:%d-%b-%Y}."
        return {"text": text, "table": {"header": ["Employee", "Name", "Department", "First in"],
                                        "rows": [[r["employee_code"], r["employee_name"], r["department_code"], r["first_in"]] for r in rows]},
                "run": info}

    if intent == "COMPARE_PERIODS":
        series = analytics.trend(session, principal, rules, d - timedelta(days=14), d)
        if len(series) < 2:
            return {"text": "At least two processed reporting dates are needed for a comparison.", "table": None, "run": info}
        a, b = series[-2], series[-1]
        text = (f"{b['date']} vs {a['date']}: present {b['counts']['PRESENT']} vs {a['counts']['PRESENT']}, "
                f"absent {b['counts']['ABSENT']} vs {a['counts']['ABSENT']}, eligible {b['eligible']} vs {a['eligible']}.")
        return {"text": text, "table": {"header": ["Date", "Eligible", "Present", "Absent", "Attendance %"],
                                        "rows": [[x["date"], x["eligible"], x["counts"]["PRESENT"], x["counts"]["ABSENT"],
                                                  _pct(x["attendance_pct"])] for x in (a, b)]}, "run": info}

    if intent == "SOURCE_CONFLICTS":
        if not has_permission(principal, Perm.RECONCILIATION_VIEW):
            return {"text": "You are not authorised to view reconciliation results.", "table": None, "run": info}
        rows = analytics.reconciliation_rows(session, principal, run.run_id)
        counts = Counter(r["category"] for r in rows if r["category"] != "MATCHED")
        text = (f"On {d:%d-%b-%Y}: {counts.get('BIZOM_ONLY', 0)} Bizom-only, {counts.get('HRMS_ONLY', 0)} Pocket HRMS-only, "
                f"{counts.get('STATUS_CONFLICT', 0)} status conflicts and {counts.get('EMPLOYEE_MAPPING_MISSING', 0)} unmapped ids.")
        return {"text": text, "table": {"header": ["Category", "Count"], "rows": [[k, v] for k, v in counts.most_common()]}, "run": info}

    # DEPARTMENT_TREND
    series = analytics.trend(session, principal, rules, d - timedelta(days=13), d)
    text = (f"{len(series)} processed day(s) between {(d - timedelta(days=13)):%d-%b-%Y} and {d:%d-%b-%Y} in your scope. "
            + (f"Absences moved from {series[0]['counts']['ABSENT']} to {series[-1]['counts']['ABSENT']}." if series else ""))
    return {"text": text, "table": {"header": ["Date", "Eligible", "Present", "Absent"],
                                    "rows": [[x["date"], x["eligible"], x["counts"]["PRESENT"], x["counts"]["ABSENT"]] for x in series]},
            "run": info}


def ask(session: Session, settings: Settings, principal: Principal, question: str, client: OllamaClient | None = None) -> dict:
    if not has_permission(principal, Perm.AI_USE):
        raise AuthorizationError("analyst not permitted")
    t0 = time.perf_counter()
    parsed = parse(question)
    if parsed.intent is None:
        result = {"text": "I can answer these questions: " + " | ".join(INTENTS.values()), "table": None, "run": None}
        status = "UNSUPPORTED"
    else:
        result = _answer(session, principal, settings, parsed.intent, parsed.day)
        status = "OK"
        if settings.features.ai_enabled and result.get("run"):
            try:
                facts = {"answer": result["text"], "table": result["table"]}
                prompt = ("Re-phrase this attendance answer for a manager in at most 60 words. Use only these numbers. "
                          f'Respond as JSON {{"text": "..."}}.\nDATA: {json.dumps(facts)}')
                raw = (client or OllamaClient(settings.ai)).generate_json(prompt)
                text = str(raw.get("text", ""))
                if text and not unsupported_numbers(text, facts) and numbers_in(text) <= numbers_in(facts):
                    result["text"], result["phrased_by_ai"] = text, True
            except AIUnavailable:
                pass
    run = result.get("run")
    result.update({"intent": parsed.intent, "supported_questions": list(INTENTS.values()),
                   "source": f"Processing run {run['run_ref']} (rule version {run['rule_version']}"
                             f"{', provisional' if not run['rules_approved'] else ''})" if run else None,
                   "period": run["reporting_date"] if run else None})
    session.add(AIExecutionLog(feature="ANALYST", run_id=run["run_id"] if run else None, username=principal.username,
                               model=settings.ai.model if settings.features.ai_enabled else None, prompt_version="analyst_v1",
                               status=status, duration_ms=int((time.perf_counter() - t0) * 1000),
                               detail=json.dumps({"intent": parsed.intent, "question": question[:200]})))
    session.flush()
    return result
