"""The 'Location & selfie checks' part of the Field Sales emails, dashboards and Excel: for the people one recipient covers,
everyone with a location sign, a selfie sign or an unusual day, ranked by the learned risk score. Text only - the map and
the photos stay in the HR Portal."""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from database.models.sales import SalesDayScore, SalesDayUpload, SalesEmployee, SalesEmployeeDay, SalesPhoto
from sales.analysis import WARNINGS
from sales.config import get_rules
from sales.geo import GEO, UNUSUAL
from sales.photos import PHOTO

LEVELS = ("high", "medium", "low")


def day_checks(session: Session, day: date, codes: set[str] | None) -> list[dict]:
    """People (of `codes`, or everyone) with a location / selfie sign or an unusual day on `day`, highest risk first."""
    if not get_rules(session).geo_in_emails:
        return []
    up = session.scalar(select(SalesDayUpload).where(SalesDayUpload.report_date == day, SalesDayUpload.is_current.is_(True)))
    rows = {r.code: r for r in session.scalars(select(SalesEmployeeDay).where(SalesEmployeeDay.upload_id == up.upload_id))} if up else {}
    scores = {s.code: s for s in session.scalars(select(SalesDayScore).where(SalesDayScore.day == day))}
    photos: dict[str, list[SalesPhoto]] = defaultdict(list)
    for p in session.scalars(select(SalesPhoto).where(SalesPhoto.day == day, SalesPhoto.flags.is_not(None))):
        photos[p.code].append(p)
    staff = {e.code: e for e in session.scalars(select(SalesEmployee))}
    out = []
    for code in set(rows) | set(photos) | {c for c, s in scores.items() if s.unusual}:
        if codes is not None and code not in codes:
            continue
        r, sc = rows.get(code), scores.get(code)
        signs: list[dict] = []
        if sc is not None and sc.unusual:
            signs.append({"label": UNUSUAL[0], "level": UNUSUAL[1], "kind": "Pattern",
                          "why": "; ".join(json.loads(sc.reasons or "[]")).capitalize()})
        if r is not None and r.geo_flags:
            ev = json.loads(r.geo_evidence or "{}")
            signs += [{"label": GEO[k][0], "level": GEO[k][1], "kind": "Location", "why": ev.get(k, "")} for k in r.geo_flags.split(",") if k in GEO]
        for p in photos.get(code, []):
            ev = json.loads(p.evidence or "{}")
            signs += [{"label": PHOTO[k][0], "level": PHOTO[k][1], "kind": "Selfie", "why": ev.get(k, "")} for k in p.flags.split(",") if k in PHOTO]
        if not signs:
            continue
        e = staff.get(code)
        day_flags = [WARNINGS[f][0] for f in ((r.flags if r else "") or "").split(",") if f in WARNINGS]
        signs.sort(key=lambda s: LEVELS.index(s["level"]))
        out.append({"code": code, "name": r.name if r else (e.name if e else code), "designation": (r.designation if r else (e.designation if e else "")) or "",
                    "manager": (r.manager_name if r else (e.manager_name if e else "")) or "", "hod": (r.hod_name if r else (e.hod_name if e else "")) or "",
                    "risk": sc.risk if sc else 0, "signs": signs, "level": signs[0]["level"], "other": day_flags,
                    "why": " ".join(s["why"].rstrip(".") + "." for s in signs if s["why"])})
    out.sort(key=lambda x: (-x["risk"], LEVELS.index(x["level"]), x["name"]))
    return out


def summary(checks: list[dict]) -> list[dict]:
    c = Counter((s["kind"], s["label"], s["level"]) for x in checks for s in x["signs"])
    return [{"kind": k, "label": lab, "level": lvl, "n": n} for (k, lab, lvl), n in sorted(c.items(), key=lambda kv: (LEVELS.index(kv[0][2]), -kv[1]))]


def month_patterns(session: Session, start: date, end: date, codes: set[str] | None, repeat: int) -> dict[str, dict]:
    """Per person over a month: days with a location sign, days with a selfie sign, unusual days, highest risk - and the
    'repeated' reasons for the month-end 'Needs a conversation' list."""
    if not get_rules(session).geo_in_emails:
        return {}
    out: dict[str, dict] = defaultdict(lambda: {"location_days": 0, "selfie_days": 0, "unusual_days": 0, "max_risk": 0, "labels": Counter()})
    for d, code, g in session.execute(select(SalesDayUpload.report_date, SalesEmployeeDay.code, SalesEmployeeDay.geo_flags)
                                      .join(SalesDayUpload, SalesDayUpload.upload_id == SalesEmployeeDay.upload_id)
                                      .where(SalesDayUpload.is_current.is_(True), SalesDayUpload.report_date >= start,
                                             SalesDayUpload.report_date <= end, SalesEmployeeDay.geo_flags.is_not(None))):
        if codes is None or code in codes:
            out[code]["location_days"] += 1
            out[code]["labels"].update(GEO[k][0] for k in g.split(",") if k in GEO)
    seen = set()
    for code, d, f in session.execute(select(SalesPhoto.code, SalesPhoto.day, SalesPhoto.flags).where(
            SalesPhoto.day >= start, SalesPhoto.day <= end, SalesPhoto.flags.is_not(None))):
        if (codes is None or code in codes) and any(PHOTO[k][1] != "low" for k in f.split(",") if k in PHOTO):
            if (code, d) not in seen:
                seen.add((code, d))
                out[code]["selfie_days"] += 1
            out[code]["labels"].update(PHOTO[k][0] for k in f.split(",") if k in PHOTO and PHOTO[k][1] != "low")
    for code, unusual, risk in session.execute(select(SalesDayScore.code, SalesDayScore.unusual, SalesDayScore.risk).where(
            SalesDayScore.day >= start, SalesDayScore.day <= end)):
        if codes is None or code in codes:
            if unusual:
                out[code]["unusual_days"] += 1
            if risk > out[code]["max_risk"]:
                out[code]["max_risk"] = risk
    res = {}
    for code, v in out.items():
        reasons = []
        if v["location_days"] >= repeat:
            reasons.append(f"location signs on {v['location_days']} days")
        if v["selfie_days"] >= 2:
            reasons.append(f"selfie signs on {v['selfie_days']} days")
        if v["unusual_days"] >= repeat:
            reasons.append(f"{v['unusual_days']} unusual days")
        res[code] = {**{k: v[k] for k in ("location_days", "selfie_days", "unusual_days", "max_risk")},
                     "top": [lab for lab, _ in v["labels"].most_common(2)], "reasons": reasons}
    return res


# ---------------------------------------------------------------- proof (dashboard + Excel of HODs, Director, HR)
PROOF_ROLES = ("HOD", "Director", "HR")      # who gets selfies and map links (decided 2026-11-21: team heads get text only)


def _thumb(client, url: str) -> bytes | None:
    """A small JPEG of a Bizom selfie, made in memory for the attachment (the HR Portal stores no photos)."""
    import io

    from PIL import Image, ImageOps

    from sales import photos
    try:
        im = ImageOps.exif_transpose(Image.open(io.BytesIO(photos._download(client, url)))).convert("RGB")
        im.thumbnail((180, 240))
        buf = io.BytesIO()
        im.save(buf, "JPEG", quality=72)
        return buf.getvalue()
    except Exception:
        return None


def proof(session: Session, day: date, items: list[dict], limit: int = 40, client=None) -> list[dict]:
    """For the highest-risk people: their attendance selfie, the confirmed matching selfie(s), and map links."""
    import base64

    import httpx

    from database.models.sales import SalesLocation
    from sales import ml
    if not items:
        return []
    top = items[:limit]
    codes = {x["code"] for x in top}
    locs = {(l.code, l.kind): l for l in session.scalars(select(SalesLocation).where(SalesLocation.day == day, SalesLocation.code.in_(codes)))}
    places = ml.usual_places(session, day, get_rules(session), codes)
    selfies = {p.code: p for p in session.scalars(select(SalesPhoto).where(SalesPhoto.day == day, SalesPhoto.code.in_(codes)))}
    match_ids = {m for p in selfies.values() for m in json.loads(p.evidence or "{}").get("_matches", []) if p.flags and
                 any(k in p.flags for k in ("PHOTO_REUSED", "PHOTO_OTHER_PERSON"))}
    matched = {m.id: m for m in session.scalars(select(SalesPhoto).where(SalesPhoto.id.in_(match_ids)))} if match_ids else {}
    names = {e.code: e.name for e in session.scalars(select(SalesEmployee))}
    own = client is None
    client = client or httpx.Client(timeout=20, follow_redirects=False, headers={"User-Agent": "HR-Portal-photo-check/1.0"})
    uri = lambda b: ("data:image/jpeg;base64," + base64.b64encode(b).decode()) if b else None  # noqa: E731
    gmap = lambda l: f"https://www.google.com/maps?q={l.lat:.6f},{l.lng:.6f}" if l else None  # noqa: E731
    out = []
    try:
        for x in top:
            p = selfies.get(x["code"])
            att, eod = locs.get((x["code"], "ATT")), locs.get((x["code"], "EOD"))
            near = ml.nearest(places.get(x["code"], []), (att.lat, att.lng)) if att else None
            selfie = _thumb(client, p.url) if p else None
            ms = []
            if p and p.flags and any(k in p.flags for k in ("PHOTO_REUSED", "PHOTO_OTHER_PERSON")):
                for mid in json.loads(p.evidence or "{}").get("_matches", [])[:2]:
                    m = matched.get(mid)
                    if m:
                        ms.append({"name": names.get(m.code, m.code), "code": m.code, "date": m.day.isoformat(), "url": m.url,
                                   "jpg": _thumb(client, m.url)})
            out.append({**x, "selfie_url": p.url if p else None, "selfie_jpg": selfie, "selfie_uri": uri(selfie),
                        "matches": [{**m, "uri": uri(m["jpg"])} for m in ms],
                        "att_map": gmap(att), "att_time": att.time if att else None, "eod_map": gmap(eod),
                        "from_usual": (f"{near[0]:.1f} km from the nearest usual place" if near else None)})
    finally:
        if own:
            client.close()
    return out


# ---------------------------------------------------------------- trend and repeats for the email highlights
def context(session: Session, day: date, codes: set[str] | None) -> dict:
    """The previous uploaded day's attendance % for the same people, and who is absent several uploaded days in a row."""
    from sales.report import pct_of
    ups = list(session.scalars(select(SalesDayUpload).where(SalesDayUpload.is_current.is_(True), SalesDayUpload.report_date <= day)
                               .order_by(SalesDayUpload.report_date.desc()).limit(7)))
    if not ups or ups[0].report_date != day:
        return {}
    rows_of = {u.report_date: [r for r in session.scalars(select(SalesEmployeeDay).where(SalesEmployeeDay.upload_id == u.upload_id))
                               if codes is None or r.code in codes] for u in ups}
    out: dict = {}
    if len(ups) > 1:
        prev = ups[1].report_date
        out["prev_date"], out["prev_pct"] = prev, pct_of(rows_of[prev])
    streak: dict[str, int] = {}
    names = {}
    for r in rows_of[day]:
        if r.status == "ABSENT":
            n = 1
            for u in ups[1:]:
                st = next((x.status for x in rows_of[u.report_date] if x.code == r.code), None)
                if st != "ABSENT":
                    break
                n += 1
            if n >= 3:
                streak[r.code], names[r.code] = n, r.name
    out["streaks"] = sorted(((names[c], n) for c, n in streak.items()), key=lambda x: -x[1])
    # repeat patterns over each person's own days (plain counts, every one with its dates) - sales.patterns
    from sales import patterns
    rules = get_rules(session)
    sup = {r.code for r in rows_of[day] if (r.designation or "").upper() in {d.upper() for d in rules.supervisor_designations}}
    out["patterns"] = patterns.day_patterns(session, day, {r.code for r in rows_of[day]}, sup)
    return out
