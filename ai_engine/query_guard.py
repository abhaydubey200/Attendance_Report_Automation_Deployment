"""Natural-language question -> one of a fixed set of approved query templates (PRD 15).

No SQL is ever generated from user text. A question that matches no template is
answered with the list of supported questions.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, timedelta

from core.timeutils import today_ist

MAX_QUESTION = 300

INTENTS = {
    "OVERALL_ATTENDANCE": "What was yesterday's overall attendance?",
    "DEPARTMENT_HIGHEST_ABSENT": "Which department had the highest absenteeism?",
    "MISSING_PUNCHES": "Show employees with missing punches.",
    "COMPARE_PERIODS": "Compare the last two reporting periods.",
    "SOURCE_CONFLICTS": "Which source has the most unresolved attendance conflicts?",
    "DEPARTMENT_TREND": "Explain the department-wise attendance trend.",
}

_RULES = [
    ("MISSING_PUNCHES", r"missing\s+punch|punch(es)?\s+missing|incomplete\s+punch"),
    ("SOURCE_CONFLICTS", r"conflict|mismatch|disagree|reconcil"),
    ("COMPARE_PERIODS", r"compare|versus|\bvs\b|last two|previous (day|period)"),
    ("DEPARTMENT_HIGHEST_ABSENT", r"(highest|most|worst).*(absen)|(absen).*(highest|most|worst)"),
    ("DEPARTMENT_TREND", r"trend|over time|department[- ]wise"),
    ("OVERALL_ATTENDANCE", r"attendance|present|absent|overall|how many"),
]


@dataclass(frozen=True)
class ParsedQuestion:
    intent: str | None
    day: date | None


def parse(question: str, today: date | None = None) -> ParsedQuestion:
    q = (question or "").strip().lower()[:MAX_QUESTION]
    today = today or today_ist()
    day = None
    if "yesterday" in q:
        day = today - timedelta(days=1)
    elif "today" in q:
        day = today
    else:
        m = re.search(r"(\d{4})-(\d{2})-(\d{2})", q) or re.search(r"(\d{2})[-/](\d{2})[-/](\d{4})", q)
        if m:
            try:
                parts = [int(x) for x in m.groups()]
                day = date(parts[0], parts[1], parts[2]) if len(m.group(1)) == 4 else date(parts[2], parts[1], parts[0])
            except ValueError:
                day = None
    for intent, pattern in _RULES:
        if re.search(pattern, q):
            return ParsedQuestion(intent, day)
    return ParsedQuestion(None, day)
