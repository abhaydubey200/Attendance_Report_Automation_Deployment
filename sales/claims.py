"""Expense claim checks for Field Sales ("needs checking", never "fraud").

Input: Bizom's Claim report (one row per claim line, many days). Each line is checked against the day's attendance
(daily uploads, else the attendance history file), market activity (from the claim report itself), the attendance location
(usual start point) and the other claims. Results show in the app; the claim photos are links to Bizom's server, cleared after
keep_months.
"""

from __future__ import annotations

import json
import re
import statistics
from collections import Counter, defaultdict
from datetime import date

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from database.models.sales import SalesClaim, SalesDayUpload, SalesEmployeeDay, SalesHistoryDay, SalesLocation
from sales import bizom, geo
from sales.config import SalesRules, get_rules

CLAIM: dict[str, tuple[str, str, str]] = {
    "CLAIM_NO_ATTENDANCE": ("Claim on a day without attendance", "high",
                            "Claimed for a day the person was absent, on leave, on week off or did not mark attendance."),
    "CLAIM_DUPLICATE": ("Same claim twice", "high", "Another claim line has the same day, type, places and amount."),
    "CLAIM_ALLOWANCE_TWICE": ("Daily allowance claimed twice", "high", "A once-a-day allowance (DA / night) was claimed more than once for the day."),
    "CLAIM_IMAGE_REUSED": ("Same bill / photo on another claim", "high", "The same document, bill or odometer photo is attached to another claim."),
    "CLAIM_EXHQ_AT_HQ": ("Outstation allowance while working at HQ", "high", "An EX-HQ allowance was claimed but Bizom shows the day as work at HQ."),
    "CLAIM_EXHQ_AT_BASE": ("Outstation allowance, never left base", "high",
                           "An EX-HQ allowance was claimed but every recorded point of the day (attendance, calls, day end) is near "
                           "the usual start point."),
    "CLAIM_NO_ACTIVITY": ("Travel claimed, no market activity", "medium", "Travel or allowance claimed for a day with no calls recorded."),
    "CLAIM_SHORT_MARKET": ("Travel claimed, very little time in market", "medium", "Travel or allowance claimed for a day with very little time in market."),
    "CLAIM_HIGH_AMOUNT": ("Amount far above usual", "medium", "Much higher than the usual amount for this claim type and role."),
    "CLAIM_HALF_DAY": ("Full allowance on a half day", "low", "A daily allowance was claimed for a half day."),
    "CLAIM_LOCAL_AND_EXHQ": ("HQ local travel and outstation on one day", "low", "Both HQ local travel and an EX-HQ allowance on the same day."),
}
LEVEL = {"high": 0, "medium": 1, "low": 2}
NOT_WORKING = {"ABSENT": "absent", "LEAVE": "on leave", "WEEK_OFF": "on week off", "absent": "absent", "leave": "on leave",
               "week_off": "on week off", "not_marked": "did not mark attendance"}
HALF = {"HALF_DAY", "halfday"}
IMAGE_KEYS = ("document", "bill_1", "bill_2", "odometer_start", "odometer_end")


def kind(claim_type: str) -> str:
    t = re.sub(r"[^A-Z]", "", claim_type.upper())
    if "MOBILE" in t or "INTERNET" in t:
        return "MONTHLY"
    if t.startswith("EXHQ"):
        return "DA" if "DEARNESS" in t else "NIGHT" if "NIGHT" in t else "EXHQ_TRAVEL"
    if t.startswith("HQLOCAL"):
        return "LOCAL"
    return "OTHER"


def money(x: float) -> str:
    return f"Rs {x:,.0f}"


# ---------------------------------------------------------------- import
def import_claims(session: Session, f: bizom.BizomFile, actor: str) -> dict:
    """Add new claim lines and update existing ones (same Claimdetail_Id), then check the whole period again."""
    have = {c.detail_id: c for c in session.scalars(select(SalesClaim).where(SalesClaim.detail_id.in_([c.detail_id for c in f.claims])))}
    added = updated = 0
    for c in f.claims:
        images = {k: getattr(c, k) for k in IMAGE_KEYS if getattr(c, k)}
        vals = dict(claim_id=c.claim_id, code=c.code, name=c.name, designation=c.designation, day=c.day, submit_date=c.submit_date,
                    claim_type=c.claim_type, present_type=c.present_type, mode=c.mode, from_place=c.from_place, to_place=c.to_place,
                    amount=c.amount, approved_amount=c.approved_amount, approval_status=c.approval_status, approver=c.approver,
                    images=json.dumps(images) if images else None, calls=c.calls, orders=c.orders, sales_value=c.sales_value,
                    market_minutes=c.market_minutes, imported_by=actor)
        row = have.get(c.detail_id)
        if row is None:
            session.add(SalesClaim(detail_id=c.detail_id, **vals))
            added += 1
        else:
            for k, v in vals.items():
                setattr(row, k, v)
            updated += 1
    session.flush()
    start, end = min(c.day for c in f.claims), max(c.day for c in f.claims)
    stats = check(session, start, end)
    return {"from": start.isoformat(), "to": end.isoformat(), "rows": len(f.claims), "added": added, "updated": updated,
            "skipped": f.skipped, **stats}


# ---------------------------------------------------------------- checks
def _attendance(session: Session, start: date, end: date) -> tuple[dict[tuple[str, date], str], set[date]]:
    """(code, day) -> status. Daily uploads win over the history file. Also the days we have any attendance data for."""
    out: dict[tuple[str, date], str] = {}
    covered: set[date] = set()
    for code, d, st in session.execute(select(SalesHistoryDay.code, SalesHistoryDay.day, SalesHistoryDay.status)
                                       .where(SalesHistoryDay.day >= start, SalesHistoryDay.day <= end)):
        out[(code, d)] = st
        covered.add(d)
    for d, code, st in session.execute(select(SalesDayUpload.report_date, SalesEmployeeDay.code, SalesEmployeeDay.status)
                                       .join(SalesDayUpload, SalesDayUpload.upload_id == SalesEmployeeDay.upload_id)
                                       .where(SalesDayUpload.is_current.is_(True), SalesDayUpload.report_date >= start,
                                              SalesDayUpload.report_date <= end)):
        out[(code, d)] = st
        covered.add(d)
    return out, covered


def check(session: Session, start: date, end: date, rules: SalesRules | None = None) -> dict:
    rules = rules or get_rules(session)
    session.flush()
    claims = list(session.scalars(select(SalesClaim).where(SalesClaim.day >= start, SalesClaim.day <= end)))
    att, covered = _attendance(session, start, end)
    supervisors = {d.strip().upper() for d in rules.supervisor_designations}
    # usual amounts per claim type + role (all stored claims, not only this period)
    peers: dict[tuple[str, str], list[float]] = defaultdict(list)
    for t, des, amt in session.execute(select(SalesClaim.claim_type, SalesClaim.designation, SalesClaim.amount)):
        peers[(t, des or "")].append(amt)
    usual = {k: statistics.median(v) for k, v in peers.items() if len(v) >= rules.claim_high_min_peers}
    # images used on more than one claim line (any period)
    seen_img: dict[str, set[str]] = defaultdict(set)
    for did, imgs in session.execute(select(SalesClaim.detail_id, SalesClaim.images).where(SalesClaim.images.is_not(None))):
        for url in json.loads(imgs).values():
            seen_img[url].add(did)
    same_line = Counter((c.code, c.day, c.claim_type, (c.from_place or "").lower(), (c.to_place or "").lower(), c.amount) for c in claims)
    per_day: dict[tuple[str, date], list[SalesClaim]] = defaultdict(list)
    for c in claims:
        per_day[(c.code, c.day)].append(c)
    # attendance points + usual start for the outstation-at-base check
    # every known point of the day (attendance, calls, day end) - only days with more than the attendance point count, because
    # people often mark attendance at home before travelling
    from database.models.sales import SalesCall
    pts: dict[tuple[str, date], list[tuple[float, float]]] = defaultdict(list)
    for code, d, la, lo in session.execute(select(SalesLocation.code, SalesLocation.day, SalesLocation.lat, SalesLocation.lng)
                                           .where(SalesLocation.day >= start, SalesLocation.day <= end)):
        pts[(code, d)].append((la, lo))
    for code, d, la, lo in session.execute(select(SalesCall.code, SalesCall.day, SalesCall.lat, SalesCall.lng)
                                           .where(SalesCall.day >= start, SalesCall.day <= end, SalesCall.lat.is_not(None))):
        pts[(code, d)].append((la, lo))
    locs = {k: v for k, v in pts.items() if len(v) >= 2}
    starts_cache: dict[date, dict] = {}
    for d in sorted({c.day for c in claims if (c.code, c.day) in locs}):     # one usual-start table per day, read up front
        starts_cache[d] = geo.usual_starts(session, d, rules)
    stats: Counter = Counter()
    with session.no_autoflush:
        _check_lines(claims, att, covered, supervisors, usual, seen_img, same_line, per_day, locs, starts_cache, rules, stats)
    session.flush()
    flagged = [c for c in claims if c.flags]
    return {"checked": len(claims), "flagged_lines": len(flagged), "flagged_amount": round(sum(c.amount for c in flagged)),
            "signs": dict(stats)}


def _check_lines(claims, att, covered, supervisors, usual, seen_img, same_line, per_day, locs, starts_cache, rules, stats) -> None:
    for c in claims:
        k = kind(c.claim_type)
        f: dict[str, str] = {}
        if k != "MONTHLY":
            st = att.get((c.code, c.day))
            if st in NOT_WORKING or (st is None and c.day in covered):
                f["CLAIM_NO_ATTENDANCE"] = (f"{money(c.amount)} claimed; the person {NOT_WORKING.get(st, 'has no attendance record')}"
                                            f" on {c.day:%d-%b}.")
            elif st in HALF and k in ("DA", "NIGHT"):
                f["CLAIM_HALF_DAY"] = f"{c.claim_type} ({money(c.amount)}) on a half day."
        if same_line[(c.code, c.day, c.claim_type, (c.from_place or "").lower(), (c.to_place or "").lower(), c.amount)] > 1:
            f["CLAIM_DUPLICATE"] = f"{c.claim_type} {money(c.amount)}" + (f" {c.from_place} to {c.to_place}" if c.from_place else "") + \
                                   " appears more than once for this day."
        day_claims = per_day[(c.code, c.day)]
        if k in ("DA", "NIGHT") and sum(1 for x in day_claims if kind(x.claim_type) == k) > 1:
            f["CLAIM_ALLOWANCE_TWICE"] = f"{c.claim_type} claimed {sum(1 for x in day_claims if kind(x.claim_type) == k)} times for {c.day:%d-%b}."
        if c.images:
            reused = sorted({d for url in json.loads(c.images).values() for d in seen_img[url]} - {c.detail_id})
            if reused:
                f["CLAIM_IMAGE_REUSED"] = f"The same photo is attached to {len(reused)} other claim line(s) (e.g. #{reused[0]})."
        if k in ("DA", "NIGHT", "EXHQ_TRAVEL"):
            pt = (c.present_type or "").upper()
            if pt.endswith(" HQ") and "EX-HQ" not in pt:
                f["CLAIM_EXHQ_AT_HQ"] = f"{c.claim_type} {money(c.amount)} while Bizom shows \"{c.present_type}\"."
            day_pts = locs.get((c.code, c.day))
            us = starts_cache.get(c.day, {}).get(c.code) if day_pts else None
            if us:
                far = max(geo.km(p, (us[0], us[1])) for p in day_pts)
                if far <= rules.claim_base_km:
                    f["CLAIM_EXHQ_AT_BASE"] = (f"All {len(day_pts)} recorded points of the day were within {far:.1f} km of the usual "
                                               "start point.")
            if any(kind(x.claim_type) == "LOCAL" for x in day_claims):
                f["CLAIM_LOCAL_AND_EXHQ"] = "HQ local travel is also claimed for this day."
        if k in ("DA", "NIGHT", "EXHQ_TRAVEL", "LOCAL") and (c.designation or "").strip().upper() not in supervisors:
            if c.calls is None and c.market_minutes is None:
                f["CLAIM_NO_ACTIVITY"] = "No calls or market time recorded for this day."
            elif c.market_minutes is not None and c.market_minutes < rules.claim_short_market_minutes:
                f["CLAIM_SHORT_MARKET"] = f"{c.market_minutes} minutes in market, {c.calls or 0} calls."
        u = usual.get((c.claim_type, c.designation or ""))
        if u and c.amount > rules.claim_high_ratio * u and c.amount - u >= rules.claim_high_extra:
            f["CLAIM_HIGH_AMOUNT"] = f"{money(c.amount)} against a usual {money(u)} for {c.claim_type} ({c.designation})."
        order = sorted(f, key=lambda x: (LEVEL[CLAIM[x][1]], x))
        c.flags = ",".join(order) or None
        c.evidence = json.dumps({x: f[x] for x in order}) if order else None
        stats.update(order)


def purge_images(session: Session, before: date) -> int:
    return session.execute(update(SalesClaim).where(SalesClaim.day < before, SalesClaim.images.is_not(None)).values(images=None)).rowcount


# ---------------------------------------------------------------- reading
def labels(c: SalesClaim) -> list[dict]:
    ev = json.loads(c.evidence or "{}")
    return [{"code": k, "label": CLAIM[k][0], "level": CLAIM[k][1], "why": CLAIM[k][2], "evidence": ev.get(k, ""), "kind": "claim"}
            for k in (c.flags or "").split(",") if k in CLAIM]


def claim_dict(c: SalesClaim) -> dict:
    return {"id": c.detail_id, "claim_id": c.claim_id, "code": c.code, "name": c.name, "designation": c.designation or "",
            "date": c.day.isoformat(), "submitted": c.submit_date.isoformat() if c.submit_date else None, "type": c.claim_type,
            "present_type": c.present_type or "", "mode": c.mode or "", "from": c.from_place or "", "to": c.to_place or "",
            "amount": c.amount, "approved": c.approved_amount, "status": c.approval_status or "", "approver": c.approver or "",
            "images": json.loads(c.images) if c.images else {}, "calls": c.calls, "orders": c.orders, "market_minutes": c.market_minutes,
            "signs": labels(c)}


def for_day(session: Session, code: str, day: date) -> list[dict]:
    return [claim_dict(c) for c in session.scalars(select(SalesClaim).where(SalesClaim.code == code, SalesClaim.day == day)
                                                    .order_by(SalesClaim.claim_type, SalesClaim.detail_id))]


def overview(session: Session, start: date, end: date, visible: set[str] | None, sign: str = "", q: str = "") -> dict:
    rows = [c for c in session.scalars(select(SalesClaim).where(SalesClaim.day >= start, SalesClaim.day <= end)
                                       .order_by(SalesClaim.day, SalesClaim.code))
            if visible is None or c.code in visible]
    flagged = [c for c in rows if c.flags]
    by_sign: Counter = Counter()
    amt_sign: Counter = Counter()
    for c in flagged:
        for k in c.flags.split(","):
            by_sign[k] += 1
            amt_sign[k] += c.amount
    ql = q.strip().lower()
    shown = [c for c in flagged if (not sign or sign in c.flags.split(",")) and (not ql or ql in c.name.lower() or ql in c.code.lower())]
    shown.sort(key=lambda c: (min(LEVEL[CLAIM[k][1]] for k in c.flags.split(",")), -c.amount))
    people: Counter = Counter()
    for c in flagged:
        people[c.code] += c.amount
    return {"from": start.isoformat(), "to": end.isoformat(), "lines": len(rows), "amount": round(sum(c.amount for c in rows)),
            "flagged_lines": len(flagged), "flagged_amount": round(sum(c.amount for c in flagged)), "people": len(people),
            "signs": [{"code": k, "label": CLAIM[k][0], "level": CLAIM[k][1], "why": CLAIM[k][2], "n": n, "amount": round(amt_sign[k])}
                      for k, n in sorted(by_sign.items(), key=lambda kv: (LEVEL[CLAIM[kv[0]][1]], -kv[1]))],
            "claims": [claim_dict(c) for c in shown[:2000]], "shown": len(shown)}


def flagged_days(session: Session, start: date, end: date) -> dict[tuple[str, date], list[SalesClaim]]:
    out: dict[tuple[str, date], list[SalesClaim]] = defaultdict(list)
    for c in session.scalars(select(SalesClaim).where(SalesClaim.day >= start, SalesClaim.day <= end, SalesClaim.flags.is_not(None))):
        out[(c.code, c.day)].append(c)
    return out
