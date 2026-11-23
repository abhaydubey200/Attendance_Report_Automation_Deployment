"""Learning from HR's reviews (reward feedback) so the risk score gets more accurate over time.

Every reviewed case is a reward signal for the warning signs it had: "Action taken" = the signs were right (reward 1),
"Checked - OK" = they were a false alarm (reward 0).

1. Reliability per sign - each sign keeps a Beta(a, b) belief of "how often this sign is right", starting from its level
   (high ~60 %, medium ~30 %, low ~10 %, worth 4 reviews) and updated by every review.
2. Risk score - the chance that at least one of the day's signs is right (noisy-OR of the learned reliabilities, plus the
   unusual-day score), 0-100. Signs that keep proving false lose weight by themselves.
3. Exploration (as in bandit learning) - the Needs checking list is ordered by an optimistic risk (each sign's reliability
   plus its uncertainty), so signs with few reviews are surfaced, reviewed and learned faster; those cases are marked.
4. Learned model - with 50+ reviews (10+ of each outcome) a logistic-regression model trained on all signs and the unusual-day
   score takes over the risk score; its cross-validated accuracy (AUC) is shown.

State is kept in app_setting 'sales_learning'. Nothing here sends anything; it only re-orders and re-scores.
"""

from __future__ import annotations

import json
import math
from collections import defaultdict
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from core.timeutils import now_utc
from database.models.daily import AppSetting
from database.models.sales import SalesCase, SalesDayScore

KEY = "sales_learning"
PRIOR = {"high": 0.6, "medium": 0.3, "low": 0.1}
PRIOR_N = 4.0                          # the starting belief counts as 4 reviews
FEW = 5                                # fewer reviews than this: the sign still "helps the model learn"
MODEL_MIN, MODEL_MIN_EACH = 50, 10
UNUSUAL = "UNUSUAL_DAY"


def _all_signs() -> dict[str, tuple[str, str]]:
    """code -> (label, level) for every sign the risk score can see."""
    from sales.analysis import WARNINGS
    from sales.geo import GEO
    from sales.photos import PHOTO
    out = {k: (v[0], v[1]) for k, v in {**WARNINGS, **GEO, **PHOTO}.items()}
    out[UNUSUAL] = ("Unusual day for this person", "medium")
    return out


def state(session: Session) -> dict:
    row = session.get(AppSetting, KEY)
    return json.loads(row.value) if row else {"signs": {}, "model": None, "labels": 0, "updated_at": None}


def _save(session: Session, st: dict, actor: str = "learning") -> None:
    row = session.get(AppSetting, KEY) or AppSetting(key=KEY)
    row.value, row.updated_by = json.dumps(st), actor
    session.add(row)
    session.flush()


def belief(st: dict, code: str, level: str) -> tuple[float, float]:
    """Beta(a, b) for a sign: the level's starting belief plus the reviews."""
    s = st.get("signs", {}).get(code, {})
    p = PRIOR.get(level, 0.2)
    return p * PRIOR_N + s.get("action", 0), (1 - p) * PRIOR_N + s.get("ok", 0)


def reliability(st: dict, code: str, level: str) -> float:
    a, b = belief(st, code, level)
    return a / (a + b)


def optimistic(st: dict, code: str, level: str) -> float:
    a, b = belief(st, code, level)
    mean = a / (a + b)
    sd = math.sqrt(a * b / ((a + b) ** 2 * (a + b + 1)))
    return min(0.99, mean + sd)


def risk(st: dict, signs: list[tuple[str, str]], anomaly: float | None, unusual: bool, explore: bool = False) -> int:
    """0-100. Learned model when trained, else noisy-OR of the learned sign reliabilities (+ a little for an unusual pattern)."""
    codes = {c for c, _ in signs} | ({UNUSUAL} if unusual else set())
    m = st.get("model")
    if m and not explore:
        z = m["intercept"] + sum(m["coef"].get(c, 0.0) for c in codes) + m["coef"].get("_anomaly", 0.0) * (anomaly or 0.0)
        return round(100 / (1 + math.exp(-z)))
    levels = dict(signs)
    levels[UNUSUAL] = "medium"
    miss = 1.0
    for c in codes:
        p = (optimistic if explore else reliability)(st, c, levels.get(c, "low"))
        miss *= 1 - p
    if anomaly is not None and not unusual:
        miss *= 1 - 0.1 * anomaly                     # a slightly odd day adds at most 10
    return round(100 * (1 - miss))


def needs_reviews(st: dict, signs: list[tuple[str, str]], unusual: bool) -> bool:
    codes = {c for c, _ in signs} | ({UNUSUAL} if unusual else set())
    sig = st.get("signs", {})
    return any(sig.get(c, {}).get("action", 0) + sig.get(c, {}).get("ok", 0) < FEW for c in codes)


# ---------------------------------------------------------------- learning from the reviews
def learn(session: Session) -> dict:
    """Rebuild the beliefs (and, with enough reviews, the model) from every reviewed case."""
    from sales import ml
    reviews = list(session.scalars(select(SalesCase).where(SalesCase.status.in_(("OK", "ACTION")))))
    st = {"signs": {}, "model": None, "labels": len(reviews), "updated_at": now_utc().isoformat()}
    if not reviews:
        _save(session, st)
        return summary(session, st)
    lo, hi = min(r.day for r in reviews), max(r.day for r in reviews)
    signs = ml._signs(session, lo, hi)
    scores = {(s.code, s.day): s for s in session.scalars(select(SalesDayScore).where(SalesDayScore.day >= lo, SalesDayScore.day <= hi))}
    counts: dict[str, dict[str, int]] = defaultdict(lambda: {"action": 0, "ok": 0})
    rows, ys = [], []
    for r in reviews:
        sc = scores.get((r.code, r.day))
        codes = {c for c, _ in signs.get((r.code, r.day), [])} | ({UNUSUAL} if sc is not None and sc.unusual else set())
        outcome = "action" if r.status == "ACTION" else "ok"
        for c in codes:
            counts[c][outcome] += 1
        rows.append((codes, (sc.anomaly or 0.0) if sc else 0.0))
        ys.append(1 if r.status == "ACTION" else 0)
    st["signs"] = dict(counts)
    if len(ys) >= MODEL_MIN and min(sum(ys), len(ys) - sum(ys)) >= MODEL_MIN_EACH:
        st["model"] = _train(rows, ys)
    _save(session, st)
    return summary(session, st)


def _train(rows: list[tuple[set[str], float]], ys: list[int]) -> dict:
    import numpy as np
    from sklearn.linear_model import LogisticRegression
    from sklearn.model_selection import cross_val_score
    vocab = sorted({c for codes, _ in rows for c in codes})
    x = np.array([[1.0 if c in codes else 0.0 for c in vocab] + [anom] for codes, anom in rows])
    y = np.array(ys)
    clf = LogisticRegression(C=1.0, class_weight="balanced", max_iter=1000)
    folds = min(5, int(min(y.sum(), len(y) - y.sum())))
    auc = float(np.mean(cross_val_score(clf, x, y, cv=folds, scoring="roc_auc"))) if folds >= 2 else None
    clf.fit(x, y)
    coef = {c: float(w) for c, w in zip(vocab + ["_anomaly"], clf.coef_[0])}
    return {"coef": coef, "intercept": float(clf.intercept_[0]), "trained_on": len(ys), "auc": round(auc, 3) if auc is not None else None,
            "trained_at": now_utc().isoformat()}


def summary(session: Session, st: dict | None = None) -> dict:
    st = st or state(session)
    names = _all_signs()
    rows = []
    for code, (label, level) in names.items():
        s = st.get("signs", {}).get(code, {})
        n = s.get("action", 0) + s.get("ok", 0)
        rows.append({"code": code, "label": label, "level": level, "reviewed": n, "action": s.get("action", 0), "ok": s.get("ok", 0),
                     "start": round(100 * PRIOR[level]), "learned": round(100 * reliability(st, code, level)),
                     "weight": round(st["model"]["coef"].get(code, 0.0), 2) if st.get("model") else None})
    rows.sort(key=lambda r: (-r["reviewed"], ("high", "medium", "low").index(r["level"]), r["label"]))
    m = st.get("model")
    from sales.config import get_rules
    off = set(get_rules(session).disabled_signs)
    weak = set(weak_signs(st))
    from sales import trust
    for r in rows:
        r["switched_off"], r["suggest_off"] = r["code"] in off, r["code"] in weak and r["code"] not in off
        r["judgment"], r["in_emails"], r["email_status"] = r["code"] in trust.JUDGMENT, trust.in_emails(st, r["code"]), trust.status(st, r["code"])
    return {"labels": st.get("labels", 0), "updated_at": st.get("updated_at"), "reasons": REASONS,
            "mode": "model" if m else "feedback", "model": {k: m[k] for k in ("trained_on", "auc", "trained_at")} if m else None,
            "needed_for_model": {"reviews": MODEL_MIN, "each_outcome": MODEL_MIN_EACH}, "signs": rows,
            "email_rule": "Measured facts always go to HODs. Signs that compare a day with what the app learned go to HODs only "
                          "after HR's reviews show them right at least 90% of the time over 8+ reviews; until then HR sees them."}


def last_review_day(session: Session) -> date | None:
    return session.scalar(select(SalesCase.day).order_by(SalesCase.day.desc()).limit(1))


# ---------------------------------------------------------------- track record + calibration
REASONS = {"APPROVED_TOUR": "Approved tour / outstation", "GPS_ERROR": "GPS or app error", "DATA_WRONG": "Staff list or data wrong",
           "REAL_ISSUE": "Real issue", "OTHER": "Other"}
WEAK_BELOW, WEAK_MIN_REVIEWS = 25, 5             # a sign right < 25 % of the time over 5+ reviews is suggested for switching off


def record(st: dict, code: str) -> str | None:
    s = st.get("signs", {}).get(code, {})
    n = s.get("action", 0) + s.get("ok", 0)
    return f"right {s.get('action', 0)} of {n} times when checked" if n >= 3 else None


def add_records(st: dict, signs: list[dict]) -> list[dict]:
    for s in signs:
        s["record"] = record(st, s["code"])
    return signs


def weak_signs(st: dict) -> list[str]:
    out = []
    for code, s in st.get("signs", {}).items():
        n = s.get("action", 0) + s.get("ok", 0)
        if n >= WEAK_MIN_REVIEWS and 100 * s.get("action", 0) / n < WEAK_BELOW:
            out.append(code)
    return out
