"""Executive summary generation (PRD 14). Optional: any failure returns False and the
run continues (AI_UNAVAILABLE). Output is validated: structure via Pydantic, and every
number in the text must exist in the context -- otherwise the summary is REJECTED."""

from __future__ import annotations

import json
import re
import time
from pathlib import Path

from pydantic import BaseModel, Field, ValidationError
from sqlalchemy.orm import Session

from ai_engine.context_builder import numbers_in, run_context
from ai_engine.ollama_client import AIUnavailable, OllamaClient
from core.config import Settings
from database.models.attendance import ProcessingRun
from database.models.audit import AIExecutionLog
from database.models.reporting import AISummary

PROMPT_FILE = Path(__file__).parent / "prompts" / "summary_v1.txt"
PROMPT_VERSION = "summary_v1"


class SummaryOutput(BaseModel):
    summary: str = Field(min_length=10, max_length=1500)
    highlights: list[str] = Field(default_factory=list, max_length=4)


def unsupported_numbers(text: str, context: dict) -> list[str]:
    allowed = numbers_in(context)
    found = re.findall(r"\d+(?:\.\d+)?", text)
    return [n for n in found if n not in allowed and n.rstrip("0").rstrip(".") not in allowed]


def generate_run_summary(session: Session, settings: Settings, run_id: int, client: OllamaClient | None = None) -> bool:
    run = session.get(ProcessingRun, run_id)
    context = run_context(session, run)
    t0 = time.perf_counter()
    status, detail, text = "UNAVAILABLE", None, None
    if not settings.features.ai_enabled:
        status, detail = "DISABLED", "AI disabled in configuration"
    else:
        prompt = PROMPT_FILE.read_text(encoding="utf-8").replace("{context}", json.dumps(context, indent=1))
        try:
            raw = (client or OllamaClient(settings.ai)).generate_json(prompt)
            out = SummaryOutput.model_validate(raw)
            text = out.summary + ("\n- " + "\n- ".join(out.highlights) if out.highlights else "")
            bad = unsupported_numbers(text, context)
            if bad:
                status, detail, text = "REJECTED", f"numbers not in validated metrics: {bad[:10]}", None
            else:
                status = "OK"
        except AIUnavailable as exc:
            detail = str(exc)
        except ValidationError as exc:
            status, detail = "REJECTED", f"invalid structure: {exc.error_count()} errors"
    session.add(AIExecutionLog(feature="SUMMARY", run_id=run_id, model=settings.ai.model, prompt_version=PROMPT_VERSION,
                               status=status, duration_ms=int((time.perf_counter() - t0) * 1000), detail=detail))
    session.add(AISummary(run_id=run_id, scope="ORG", status="GENERATED" if status == "OK" else status,
                          summary=text, context=json.dumps(context, default=str), model=settings.ai.model,
                          prompt_version=PROMPT_VERSION))
    session.flush()
    return status == "OK"
