"""Which warning signs may go into the emails of HODs, team heads and the Director.

* FACT signs state something measured in Bizom's own data (hours in market, distance from the outlet, the same GPS point
  as someone else, a selfie confirmed identical by image comparison ...). The statement is true by construction.
* JUDGMENT signs compare a day with what the app has LEARNED (usual places, the unusual-day model, how a selfie looks).
  They go to HODs only once HR's reviews show they are right often enough: at least MIN_REVIEWS reviews and at least
  MIN_PRECISION of them "needs action". Until then they stay in HR's email and in the HR Portal, where HR reviews them.
"""

from __future__ import annotations

JUDGMENT = {"GEO_START_AWAY", "GEO_AWAY_AT_HQ", "UNUSUAL_DAY", "PHOTO_NOT_LIVE", "PHOTO_NO_FACE", "PHOTO_POOR"}
MIN_REVIEWS = 8
MIN_PRECISION = 0.90
FULL_ROLES = ("HR",)                 # HR sees every sign (HR is the reviewer)


def precision(st: dict, code: str) -> tuple[int, float | None]:
    s = st.get("signs", {}).get(code, {})
    n = s.get("action", 0) + s.get("ok", 0)
    return n, (s.get("action", 0) / n if n else None)


def proven(st: dict, code: str) -> bool:
    n, p = precision(st, code)
    return n >= MIN_REVIEWS and p is not None and p >= MIN_PRECISION


def in_emails(st: dict, code: str) -> bool:
    return code not in JUDGMENT or proven(st, code)


def status(st: dict, code: str) -> str:
    """Plain words for the learning screen."""
    if code not in JUDGMENT:
        return "In HOD emails (measured fact)"
    n, p = precision(st, code)
    if proven(st, code):
        return f"In HOD emails (right {round(100 * p)}% of {n} reviews)"
    need = max(0, MIN_REVIEWS - n)
    return (f"HR only until proven: {n} review(s)" + (f", {need} more needed" if need else f", right {round(100 * p)}% (needs {round(100 * MIN_PRECISION)}%)"))


def for_email(checks: list[dict], st: dict) -> list[dict]:
    """Keep only the signs allowed in a HOD / team-head / Director email; people left without a sign are dropped and the
    risk is worked out again from what is left (the learned anomaly score only counts once the unusual-day sign is proven)."""
    from sales import learning
    out = []
    for c in checks:
        signs = [s for s in c["signs"] if in_emails(st, s.get("code") or "")]
        if not signs:
            continue
        unusual = any(s.get("code") == "UNUSUAL_DAY" for s in signs)
        anomaly = c.get("anomaly") if in_emails(st, "UNUSUAL_DAY") else None
        risk = learning.risk(st, [(s["code"], s["level"]) for s in signs if s.get("code") != "UNUSUAL_DAY"], anomaly, unusual)
        out.append({**c, "signs": signs, "level": signs[0]["level"], "risk": risk,
                    "why": " ".join(s["why"].rstrip(".") + "." for s in signs if s["why"])})
    out.sort(key=lambda x: (-x["risk"], ("high", "medium", "low").index(x["level"]), x["name"]))
    return out
