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
