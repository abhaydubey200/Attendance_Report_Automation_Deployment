"""Minimal Ollama client (PRD 14.4): configurable endpoint/model, timeout, bounded
retries, JSON output. Raises AIUnavailable on any failure; callers fall back."""

from __future__ import annotations

import json
import time

import httpx

from core.config import AIConfig


class AIUnavailable(Exception):
    pass


class OllamaClient:
    def __init__(self, cfg: AIConfig, client: httpx.Client | None = None, sleep=time.sleep) -> None:
        self.cfg = cfg
        self.client = client or httpx.Client(timeout=cfg.timeout_seconds)
        self.sleep = sleep

    def generate_json(self, prompt: str) -> dict:
        if not self.cfg.enabled or not self.cfg.model:
            raise AIUnavailable("AI is disabled")
        last: Exception | None = None
        for attempt in range(self.cfg.max_retries + 1):
            try:
                r = self.client.post(f"{self.cfg.endpoint.rstrip('/')}/api/generate", json={
                    "model": self.cfg.model, "prompt": prompt, "stream": False, "format": "json",
                    "options": {"temperature": 0}})
                r.raise_for_status()
                return json.loads(r.json()["response"])
            except (httpx.HTTPError, KeyError, ValueError) as exc:
                last = exc
                if attempt < self.cfg.max_retries:
                    self.sleep(min(2 ** attempt, 10))
        raise AIUnavailable(f"{type(last).__name__}") from last
