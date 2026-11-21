"""Machine learning for Field Sales attendance checks ("needs checking", never "fraud").

1. Usual places - each person's attendance points of the last `geo_start_history_days` (x2) days are clustered with DBSCAN
   (haversine distance, 1 km neighbourhood). A person can have several usual places (home, HQ, depot); a day's start is
   "away" only when it is far from ALL of them.
2. Unusual day - each person-day becomes a vector of how far it is from that person's own normal (robust z-scores of
   attendance time, distance from usual places, KM, time in market, day length, calls). An Isolation Forest trained on all
   person-days scores how unusual each day is; the biggest differences become plain-language reasons.
3. Risk score 0-100 per person-day: the chance that at least one of the day's warning signs (attendance, location, selfie) is
   right, from each sign's reliability learned from HR's reviews (sales.learning), plus the unusual-day score.

The unusual-day model is unsupervised; the risk score learns from the reviews (OK / action taken) - see sales.learning.
"""

from __future__ import annotations

import json
import math
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from database.models.sales import SalesCall, SalesDayScore, SalesDayUpload, SalesEmployeeDay, SalesLocation, SalesPhoto
from sales.config import SalesRules, get_rules

EARTH_KM = 6371.0
FEATURES = ("att_min", "place_km", "km", "market_min", "day_min", "calls")


@dataclass
class Place:
    lat: float
    lng: float
    days: int
    radius_km: float          # 90% of this place's points are within this distance of its centre
    travel_km: float = 0.0    # the person's own normal: 75% of all their starts are within this distance of a usual place


def _km(a: tuple[float, float], b: tuple[float, float]) -> float:
    la1, lo1, la2, lo2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 2 * EARTH_KM * math.asin(math.sqrt(h))


# ---------------------------------------------------------------- 1. usual places (DBSCAN)
def places_of(points: list[tuple[float, float]], min_days: int = 3, eps_km: float = 1.0) -> list[Place]:
    import numpy as np
    from sklearn.cluster import DBSCAN
    if len(points) < min_days:
        return []
    x = np.radians(np.array(points))
    labels = DBSCAN(eps=eps_km / EARTH_KM, min_samples=min_days, metric="haversine", algorithm="ball_tree").fit_predict(x)
    out = []
    for lab in sorted(set(labels) - {-1}):
        pts = [p for p, l in zip(points, labels) if l == lab]
        mid = (float(np.median([p[0] for p in pts])), float(np.median([p[1] for p in pts])))
        d = sorted(_km(mid, p) for p in pts)
        out.append(Place(mid[0], mid[1], len(pts), max(0.2, d[int(0.9 * (len(d) - 1))])))
    out.sort(key=lambda p: -p.days)
    if out:                   # people who start in many different towns travel for work: a far start is normal for them
        near = sorted(min(_km((p.lat, p.lng), x) for p in out) for x in points)
        for p in out:
            p.travel_km = near[int(0.75 * (len(near) - 1))]
    return out


def usual_places(session: Session, day: date, rules: SalesRules, codes: set[str] | None = None) -> dict[str, list[Place]]:
    since = day - timedelta(days=2 * rules.geo_start_history_days)
    pts: dict[str, list[tuple[float, float]]] = defaultdict(list)
    q = select(SalesLocation.code, SalesLocation.lat, SalesLocation.lng).where(
        SalesLocation.kind == "ATT", SalesLocation.day >= since, SalesLocation.day < day)
    for code, la, lo in session.execute(q):
        if codes is None or code in codes:
            pts[code].append((la, lo))
    return {c: pl for c, v in pts.items() if len(v) >= rules.geo_start_min_days and (pl := places_of(v, min(3, rules.geo_start_min_days)))}


def nearest(places: list[Place], point: tuple[float, float]) -> tuple[float, Place] | None:
    if not places:
        return None
    return min(((_km((p.lat, p.lng), point), p) for p in places), key=lambda t: t[0])


def away_limit(place: Place, rules: SalesRules) -> float:
    return max(rules.geo_start_away_km, 3 * place.radius_km, 3 * place.travel_km)


# ---------------------------------------------------------------- 2 + 3. unusual day and risk score
def _minutes(t: str | None) -> float | None:
    return int(t[:2]) * 60 + int(t[3:5]) if t else None


def _rows(session: Session, start: date, end: date, rules: SalesRules) -> dict[tuple[str, date], dict]:
    """One feature dict per person-day (history file days have fewer features than full daily uploads)."""
    rows: dict[tuple[str, date], dict] = defaultdict(dict)
    att = {}
    for code, d, la, lo, t, kind in session.execute(select(SalesLocation.code, SalesLocation.day, SalesLocation.lat, SalesLocation.lng,
                                                           SalesLocation.time, SalesLocation.kind)
                                                    .where(SalesLocation.day >= start, SalesLocation.day <= end)):
        if kind == "ATT":
            att[(code, d)] = (la, lo)
            rows[(code, d)]["att_min"] = _minutes(t)
    # distance from the usual places (places learned once per person from the whole window: one odd day cannot form a place)
    by_code: dict[str, list[tuple[float, float]]] = defaultdict(list)
    for (code, _d), p in att.items():
        by_code[code].append(p)
    for code, pts in by_code.items():
        pl = places_of(pts, min(3, rules.geo_start_min_days)) if len(pts) >= rules.geo_start_min_days else []
        if not pl:
            continue
        for (c, d), p in att.items():
            if c == code:
                rows[(c, d)]["place_km"] = nearest(pl, p)[0]
    for d, r in session.execute(select(SalesDayUpload.report_date, SalesEmployeeDay)
                                .join(SalesDayUpload, SalesDayUpload.upload_id == SalesEmployeeDay.upload_id)
                                .where(SalesDayUpload.is_current.is_(True), SalesDayUpload.report_date >= start,
                                       SalesDayUpload.report_date <= end, SalesEmployeeDay.status.in_(("PRESENT", "LATE", "HALF_DAY")))):
        f = rows[(r.code, d)]
        f.setdefault("att_min", _minutes(r.attendance_time))
        f["km"] = r.km
        f["market_min"] = r.market_minutes
        a, e = _minutes(r.attendance_time), _minutes(r.eod_time)
        f["day_min"] = (e - a) if a is not None and e is not None and r.eod_time != "23:59" else None
        f["calls"] = r.calls
    return rows


def _robust(values: list[float]) -> tuple[float, float]:
    import numpy as np
    v = np.array(values, dtype=float)
    med = float(np.median(v))
    mad = float(np.median(np.abs(v - med))) * 1.4826
    return med, mad


SCALE_FLOOR = {"att_min": 20.0, "place_km": 2.0, "km": 10.0, "market_min": 30.0, "day_min": 30.0, "calls": 3.0}


def _reason(feat: str, x: float, med: float) -> str:
    if feat == "att_min":
        diff = x - med
        return f"attendance {abs(diff) // 60:.0f}:{abs(diff) % 60:02.0f} h {'later' if diff > 0 else 'earlier'} than usual"
    if feat == "place_km":
        return f"started {x:.0f} km from the usual places"
    if feat == "km":
        return f"{x:.0f} km travelled (usual {med:.0f})"
    if feat == "market_min":
        return f"{x // 60:.0f}:{x % 60:02.0f} h in market (usual {med // 60:.0f}:{med % 60:02.0f})"
    if feat == "day_min":
        return f"day of {x // 60:.0f}:{x % 60:02.0f} h (usual {med // 60:.0f}:{med % 60:02.0f})"
    return f"{x:.0f} calls (usual {med:.0f})"


def rescore(session: Session, end: date | None = None, rules: SalesRules | None = None) -> dict:
    """Recompute the unusual-day score and the risk score for the last 2 x history days up to `end`."""
    import numpy as np
    from sklearn.ensemble import IsolationForest
    rules = rules or get_rules(session)
    end = end or session.scalar(select(SalesLocation.day).order_by(SalesLocation.day.desc()).limit(1)) or date.today()
    start = end - timedelta(days=2 * rules.geo_start_history_days)
    rows = _rows(session, start, end, rules)
    if not rows:
        return {"scored": 0}
    # each person's own normal (robust median / spread per feature)
    per: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    for (code, _d), f in rows.items():
        for k, v in f.items():
            if v is not None:
                per[code][k].append(float(v))
    norm = {c: {k: _robust(v) for k, v in fs.items() if len(v) >= 4} for c, fs in per.items()}
    keys = list(rows)
    z = np.zeros((len(keys), len(FEATURES)))
    for i, key in enumerate(keys):
        f, nc = rows[key], norm.get(key[0], {})
        for j, feat in enumerate(FEATURES):
            v = f.get(feat)
            if v is None or feat not in nc:
                continue
            med, mad = nc[feat]
            z[i, j] = max(-10.0, min(10.0, (float(v) - med) / max(mad, SCALE_FLOOR[feat])))
            if feat == "place_km":                     # only being far from the usual places is unusual
                z[i, j] = max(0.0, z[i, j])
    model = IsolationForest(n_estimators=200, random_state=0).fit(z)
    raw = -model.score_samples(z)
    order = raw.argsort()
    pct = np.empty(len(raw))
    pct[order] = np.arange(len(raw)) / max(1, len(raw) - 1)
    signs = _signs(session, start, end)
    from sales import learning
    st = learning.state(session)
    session.execute(delete(SalesDayScore).where(SalesDayScore.day >= start, SalesDayScore.day <= end))
    unusual_n = 0
    for i, (code, d) in enumerate(keys):
        reasons = []
        nc = norm.get(code, {})
        for j in np.argsort(-np.abs(z[i])):
            feat = FEATURES[j]
            if abs(z[i, j]) >= 3 and feat in nc and rows[(code, d)].get(feat) is not None:
                reasons.append(_reason(feat, float(rows[(code, d)][feat]), nc[feat][0]))
        unusual = bool(pct[i] >= 0.98 and reasons)
        unusual_n += unusual
        s = signs.get((code, d), [])
        risk = learning.risk(st, s, float(pct[i]), unusual)
        session.add(SalesDayScore(code=code, day=d, anomaly=round(float(pct[i]), 3), unusual=unusual, risk=min(100, round(risk)),
                                  reasons=json.dumps(reasons[:3]) if reasons else None))
    for key, s in signs.items():                       # days with signs but no features (e.g. a selfie only)
        if key not in rows:
            session.add(SalesDayScore(code=key[0], day=key[1], anomaly=None, unusual=False,
                                      risk=learning.risk(st, s, None, False), reasons=None))
    session.flush()
    return {"scored": len(keys), "unusual": unusual_n, "from": start.isoformat(), "to": end.isoformat()}


def rerisk(session: Session) -> int:
    """Recompute only the risk scores (stored unusual-day scores + current signs + what was learned) - fast, after each review."""
    from sales import learning
    st = learning.state(session)
    rows = list(session.scalars(select(SalesDayScore)))
    if not rows:
        return 0
    signs = _signs(session, min(r.day for r in rows), max(r.day for r in rows))
    for r in rows:
        r.risk = learning.risk(st, signs.get((r.code, r.day), []), r.anomaly, r.unusual)
    session.flush()
    return len(rows)


def _signs(session: Session, start: date, end: date) -> dict[tuple[str, date], list[tuple[str, str]]]:
    from sales.analysis import WARNINGS
    from sales.geo import GEO
    from sales.photos import PHOTO
    out: dict[tuple[str, date], list[tuple[str, str]]] = defaultdict(list)
    for d, code, flags, geo_flags in session.execute(
            select(SalesDayUpload.report_date, SalesEmployeeDay.code, SalesEmployeeDay.flags, SalesEmployeeDay.geo_flags)
            .join(SalesDayUpload, SalesDayUpload.upload_id == SalesEmployeeDay.upload_id)
            .where(SalesDayUpload.is_current.is_(True), SalesDayUpload.report_date >= start, SalesDayUpload.report_date <= end)):
        for f in (flags or "").split(","):
            if f in WARNINGS:
                out[(code, d)].append((f, WARNINGS[f][1]))
        for f in (geo_flags or "").split(","):
            if f in GEO:
                out[(code, d)].append((f, GEO[f][1]))
    for code, d, flags in session.execute(select(SalesPhoto.code, SalesPhoto.day, SalesPhoto.flags)
                                          .where(SalesPhoto.day >= start, SalesPhoto.day <= end, SalesPhoto.flags.is_not(None))):
        for f in flags.split(","):
            if f in PHOTO:
                out[(code, d)].append((f, PHOTO[f][1]))
    return out


def scores(session: Session, day: date, codes: set[str] | None = None) -> dict[str, SalesDayScore]:
    q = select(SalesDayScore).where(SalesDayScore.day == day)
    return {s.code: s for s in session.scalars(q) if codes is None or s.code in codes}


def score_dict(s: SalesDayScore | None) -> dict:
    if s is None:
        return {"risk": 0, "unusual": False, "anomaly": None, "reasons": []}
    return {"risk": s.risk, "unusual": s.unusual, "anomaly": s.anomaly, "reasons": json.loads(s.reasons) if s.reasons else []}


def calls_points(session: Session, code: str, day: date) -> list[tuple[float, float]]:
    return [(la, lo) for la, lo in session.execute(select(SalesCall.lat, SalesCall.lng).where(
        SalesCall.code == code, SalesCall.day == day, SalesCall.lat.is_not(None)))]
