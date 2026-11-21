"""Location checks for Field Sales ("needs checking", never "fraud"): store the day's points, work out the warning signs,
serve the day map and the case reviews.

Stored for 6 months (Settings: keep_months), then deleted by `purge`: attendance / day-end points, every call with its
location, attendance photo links and the phone as a scrambled code. Outlets (business data) are kept.

Warning signs are shown in the app; they go into emails only once Settings > geo_in_emails is switched on.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import re
import statistics
from collections import Counter, defaultdict
from datetime import date, timedelta

from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from core.timeutils import now_utc
from database.models.sales import (SalesCall, SalesCase, SalesDayUpload, SalesDevice, SalesEmployee, SalesEmployeeDay,
                                   SalesHistoryDay, SalesLocation, SalesOutlet)
from sales import bizom
from sales.analysis import WARNINGS, WORKING, PersonDay
from sales.config import SalesRules, get_rules
from sales.util import utc_iso

# code: (label, level, why it matters)
GEO: dict[str, tuple[str, str, str]] = {
    "GEO_AWAY_FROM_OUTLET": ("Calls made away from the outlet", "high",
                             "The call's location is far from the outlet's own location - the visit may not have happened there."),
    "GEO_SAME_SPOT": ("All calls from one spot", "high", "Every call of the day was made from nearly the same place."),
    "GEO_ONE_SPOT_MANY_OUTLETS": ("Several outlets from one spot", "high",
                                  "Calls to different outlets were made from one spot, away from those outlets."),
    "GEO_KM_VS_ROUTE": ("KM much higher than the route", "medium", "Bizom KM is far more than the distance between the day's points."),
    "GEO_START_AWAY": ("Attendance away from the usual start", "medium", "Attendance was marked far from where this person usually starts."),
    "GEO_END_AWAY": ("Day ended away from the market", "low", "The day was ended far from the last call."),
    "GEO_OFF_BEAT": ("Calls outside the day's beat", "low", "Several calls were on a different beat from the rest of the day."),
    "GEO_SHARED_PHONE": ("Same phone as another person", "high", "Attendance was marked from the same phone as someone else that day."),
    "GEO_TOGETHER": ("With another person all day", "medium", "Most calls were made at the same place and time as another person's."),
}
LEVEL = {"high": 0, "medium": 1, "low": 2}
OPEN, OK, ACTION = "OPEN", "OK", "ACTION"
CASE_LABEL = {OPEN: "Open", OK: "Checked - OK", ACTION: "Action taken"}


def km(a: tuple[float, float], b: tuple[float, float]) -> float:
    return bizom._haversine(a[0], a[1], b[0], b[1])


def device_code(imei: str | None, secret: str = "") -> str | None:
    """The phone as a scrambled code: the same phone always gives the same code; the IMEI cannot be read back."""
    digits = re.sub(r"\W", "", imei or "").lower()
    if len(digits) < 6:
        return None
    return hmac.new(("apis-field-sales:" + secret).encode(), digits.encode(), hashlib.sha256).hexdigest()[:32]


def _secret() -> str:
    from core.config import get_settings
    k = get_settings().api.secret_key
    return k.get_secret_value() if k else ""


# ---------------------------------------------------------------- storing
def store_day(session: Session, upload: SalesDayUpload, people: list[PersonDay], calls_file: bizom.BizomFile | None) -> None:
    day = upload.report_date
    session.execute(delete(SalesLocation).where(SalesLocation.day == day, SalesLocation.source == "DAY"))
    session.execute(delete(SalesCall).where(SalesCall.day == day))
    for p in people:
        if p.status not in WORKING:
            continue
        for kind, loc, t in (("ATT", p.att_location, p.attendance_time), ("EOD", p.eod_location, p.eod_time)):
            if loc:
                session.execute(delete(SalesLocation).where(SalesLocation.code == p.code, SalesLocation.day == day,
                                                            SalesLocation.kind == kind))
                session.add(SalesLocation(code=p.code, day=day, kind=kind, lat=loc[0], lng=loc[1], time=t, source="DAY"))
    if calls_file is None:
        return
    for o in calls_file.outlets.values():
        row = session.get(SalesOutlet, o.outlet_id) or SalesOutlet(outlet_id=o.outlet_id, name=o.name or o.outlet_id)
        row.name, row.beat_id, row.beat_name, row.category, row.pincode = o.name or row.name, o.beat_id, o.beat_name, o.category, o.pincode
        if o.location:
            row.lat, row.lng = o.location
        session.add(row)
    for code, pts in calls_file.call_points.items():
        for n, c in enumerate(pts, start=1):
            o = calls_file.outlets.get(c.outlet_id or "")
            dist = round(km(c.location, o.location) * 1000) if c.location and o and o.location else c.distance_m
            session.add(SalesCall(upload_id=upload.upload_id, code=code, day=day, seq=n, call_id=c.call_id, start=c.start, end=c.end,
                                  duration_s=c.duration_s, lat=c.location[0] if c.location else None,
                                  lng=c.location[1] if c.location else None, outlet_id=c.outlet_id, beat_id=c.beat_id,
                                  distance_m=dist, productive=c.productive))
    session.flush()


def import_history(session: Session, hist: bizom.BizomFile) -> dict:
    """Bizom's multi-day AttendanceReport: attendance points (for the usual start point) and phone codes, then re-check those days."""
    secret = _secret()
    days = sorted({h.day for h in hist.history})
    have = {(c, d, k) for c, d, k in session.execute(select(SalesLocation.code, SalesLocation.day, SalesLocation.kind)
                                                     .where(SalesLocation.day >= days[0], SalesLocation.day <= days[-1]))}
    devs = {(c, d) for c, d in session.execute(select(SalesDevice.code, SalesDevice.day).where(SalesDevice.day >= days[0],
                                                                                                SalesDevice.day <= days[-1]))}
    statuses = {(c, d): x for c, d, x in session.execute(select(SalesHistoryDay.code, SalesHistoryDay.day, SalesHistoryDay)
                                                         .where(SalesHistoryDay.day >= days[0], SalesHistoryDay.day <= days[-1]))}
    added_loc = added_dev = 0
    for h in hist.history:
        if h.status:
            row = statuses.get((h.code, h.day))
            if row is None:
                row = SalesHistoryDay(code=h.code, day=h.day, status=h.status, leave=h.leave)
                session.add(row)
                statuses[(h.code, h.day)] = row
            else:
                row.status, row.leave = h.status, h.leave
        if h.location and (h.code, h.day, "ATT") not in have:
            session.add(SalesLocation(code=h.code, day=h.day, kind="ATT", lat=h.location[0], lng=h.location[1], time=h.attendance_time,
                                      source="HISTORY"))
            have.add((h.code, h.day, "ATT"))
            added_loc += 1
        dc = device_code(h.imei, secret)
        if dc and (h.code, h.day) not in devs:
            session.add(SalesDevice(code=h.code, day=h.day, device=dc))
            devs.add((h.code, h.day))
            added_dev += 1
    session.flush()
    from sales import photos
    photos_added = photos.register(session, [(h.photo_url, h.code, h.day, h.attendance_time) for h in hist.history if h.photo_url])
    rechecked = [u.report_date for u in session.scalars(select(SalesDayUpload).where(
        SalesDayUpload.is_current.is_(True), SalesDayUpload.report_date >= days[0], SalesDayUpload.report_date <= days[-1]))]
    for d in rechecked:
        check_day(session, d)
    return {"photos_added": photos_added, "from": days[0].isoformat(), "to": days[-1].isoformat(), "days": len(days), "rows": len(hist.history),
            "locations_added": added_loc, "phones_added": added_dev, "days_rechecked": len(rechecked)}


def purge(session: Session, rules: SalesRules | None = None, today: date | None = None) -> dict:
    rules = rules or get_rules(session)
    cutoff = (today or date.today()) - timedelta(days=round(rules.keep_months * 30.5))
    n_loc = session.execute(delete(SalesLocation).where(SalesLocation.day < cutoff)).rowcount
    n_dev = session.execute(delete(SalesDevice).where(SalesDevice.day < cutoff)).rowcount
    n_call = session.execute(delete(SalesCall).where(SalesCall.day < cutoff)).rowcount
    old = select(SalesDayUpload.upload_id).where(SalesDayUpload.report_date < cutoff)
    n_photo = session.execute(update(SalesEmployeeDay).where(SalesEmployeeDay.upload_id.in_(old), SalesEmployeeDay.photo_url.is_not(None))
                              .values(photo_url=None)).rowcount
    from sales import photos
    n_selfie = photos.purge(session, cutoff)
    return {"selfies": n_selfie, "before": cutoff.isoformat(), "locations": n_loc, "phones": n_dev, "calls": n_call, "photos": n_photo}


# ---------------------------------------------------------------- checks
def _calls_by_code(session: Session, day: date) -> dict[str, list[SalesCall]]:
    out: dict[str, list[SalesCall]] = defaultdict(list)
    for c in session.scalars(select(SalesCall).where(SalesCall.day == day).order_by(SalesCall.code, SalesCall.seq)):
        out[c.code].append(c)
    return out


def _locs(session: Session, day: date) -> dict[tuple[str, str], SalesLocation]:
    return {(x.code, x.kind): x for x in session.scalars(select(SalesLocation).where(SalesLocation.day == day))}


def usual_starts(session: Session, day: date, rules: SalesRules) -> dict[str, tuple[float, float, int, float]]:
    """code -> (lat, lng, earlier days, personal limit km). The limit is the larger of the Settings value and 3 x how far this
    person's start normally varies (75th percentile), so people who travel for work are not flagged every day."""
    since = day - timedelta(days=rules.geo_start_history_days)
    pts: dict[str, list[tuple[float, float]]] = defaultdict(list)
    for code, la, lo in session.execute(select(SalesLocation.code, SalesLocation.lat, SalesLocation.lng).where(
            SalesLocation.kind == "ATT", SalesLocation.day >= since, SalesLocation.day < day)):
        pts[code].append((la, lo))
    out = {}
    for c, v in pts.items():
        if len(v) < rules.geo_start_min_days:
            continue
        mid = (statistics.median(p[0] for p in v), statistics.median(p[1] for p in v))
        spread = sorted(km(mid, p) for p in v)[int(0.75 * (len(v) - 1))]
        out[c] = (mid[0], mid[1], len(v), max(rules.geo_start_away_km, 3 * spread))
    return out


def _fmt_km(x: float) -> str:
    return f"{x * 1000:.0f} m" if x < 1 else f"{x:.1f} km"


def check_day(session: Session, day: date, rules: SalesRules | None = None) -> dict[str, int]:
    """Work out the location warning signs for every working person of the current upload of `day`."""
    rules = rules or get_rules(session)
    up = session.scalar(select(SalesDayUpload).where(SalesDayUpload.report_date == day, SalesDayUpload.is_current.is_(True)))
    if up is None:
        return {}
    rows = list(session.scalars(select(SalesEmployeeDay).where(SalesEmployeeDay.upload_id == up.upload_id)))
    calls, locs = _calls_by_code(session, day), _locs(session, day)
    outlets = {o.outlet_id: o for o in session.scalars(select(SalesOutlet).where(
        SalesOutlet.outlet_id.in_({c.outlet_id for v in calls.values() for c in v if c.outlet_id})))}
    starts = usual_starts(session, day, rules)
    devices: dict[str, list[str]] = defaultdict(list)
    for code, dev in session.execute(select(SalesDevice.code, SalesDevice.device).where(SalesDevice.day == day)):
        devices[dev].append(code)
    names = {r.code: r.name for r in rows}
    together = _together(calls, rules)
    stats: Counter = Counter()
    for r in rows:
        flags: dict[str, str] = {}
        if r.status in WORKING:
            flags = _person_checks(r, calls.get(r.code, []), locs, outlets, starts.get(r.code), rules)
            for dev, codes in devices.items():
                if r.code in codes and len(set(codes)) > 1:
                    others = sorted(names.get(c, c) for c in set(codes) - {r.code})
                    flags["GEO_SHARED_PHONE"] = f"Same phone as {', '.join(others[:3])}{' and others' if len(others) > 3 else ''}."
            if r.code in together:
                other, share = together[r.code]
                flags["GEO_TOGETHER"] = f"{share:.0%} of calls at the same place and time as {names.get(other, other)}."
        order = sorted(flags, key=lambda k: (LEVEL[GEO[k][1]], k))
        r.geo_flags = ",".join(order) or None
        r.geo_evidence = json.dumps({k: flags[k] for k in order}) if order else None
        stats.update(order)
    session.flush()
    return dict(stats)


def _person_checks(r: SalesEmployeeDay, calls: list[SalesCall], locs: dict, outlets: dict, usual, rules: SalesRules) -> dict[str, str]:
    f: dict[str, str] = {}
    pts = [(c.lat, c.lng) for c in calls if c.lat is not None and c.lng is not None]
    # 1. calls away from the outlet
    away = [c.distance_m for c in calls if c.distance_m is not None and c.distance_m > rules.geo_away_outlet_m]
    if len(away) >= rules.geo_away_outlet_min:
        f["GEO_AWAY_FROM_OUTLET"] = (f"{len(away)} of {len(calls)} calls were {_fmt_km(min(away) / 1000)}"
                                     + (f" to {_fmt_km(max(away) / 1000)}" if max(away) != min(away) else "") + " from the outlet.")
    # 2. all calls from one spot
    if len(pts) >= rules.geo_same_spot_min_calls:
        mid = (statistics.mean(p[0] for p in pts), statistics.mean(p[1] for p in pts))
        spread = max(km(mid, p) for p in pts) * 1000
        if spread <= rules.geo_same_spot_m:
            f["GEO_SAME_SPOT"] = f"All {len(pts)} calls within {spread:.0f} m of one spot."
    # 3. several outlets from one spot (the outlets themselves being away from that spot)
    far = [c for c in calls if c.lat is not None and c.distance_m is not None and c.distance_m > rules.geo_cluster_outlet_far_m]
    best = 0
    for c in far:
        near = {x.outlet_id for x in far if km((c.lat, c.lng), (x.lat, x.lng)) * 1000 <= rules.geo_cluster_m}
        best = max(best, len(near))
    if best >= rules.geo_cluster_outlets:
        f["GEO_ONE_SPOT_MANY_OUTLETS"] = f"{best} different outlets logged from within {rules.geo_cluster_m:.0f} m of one spot."
    # 4. KM vs route (attendance -> calls -> day end)
    path = ([(locs[(r.code, "ATT")].lat, locs[(r.code, "ATT")].lng)] if (r.code, "ATT") in locs else []) + pts + \
           ([(locs[(r.code, "EOD")].lat, locs[(r.code, "EOD")].lng)] if (r.code, "EOD") in locs else [])
    if r.km and len(pts) >= 3:              # needs real call points: start -> end alone says nothing about the route
        route = sum(km(a, b) for a, b in zip(path, path[1:]))
        if r.km > rules.geo_km_ratio * route and r.km - route >= rules.geo_km_extra:
            f["GEO_KM_VS_ROUTE"] = f"Bizom KM {r.km:.0f} km; route between the day's {len(path)} points {route:.1f} km."
    # 5. attendance away from the usual start
    att = locs.get((r.code, "ATT"))
    if att and usual:
        d = km((att.lat, att.lng), (usual[0], usual[1]))
        if d > usual[3]:
            f["GEO_START_AWAY"] = f"Attendance {d:.1f} km from the usual start point ({usual[2]} earlier days)."
    # 6. day ended away from the market
    eod = locs.get((r.code, "EOD"))
    if eod and pts:
        d = km((eod.lat, eod.lng), pts[-1])
        if d > rules.geo_end_away_km:
            f["GEO_END_AWAY"] = f"Day ended {d:.1f} km from the last call."
    # 7. calls outside the day's main beat
    beats = Counter(c.beat_id for c in calls if c.beat_id)
    if len(beats) > 1:
        main, n_main = beats.most_common(1)[0]
        off = sum(beats.values()) - n_main
        if off >= rules.geo_offbeat_min:
            name = outlets.get(next((c.outlet_id for c in calls if c.beat_id == main), ""), None)
            f["GEO_OFF_BEAT"] = f"{off} of {sum(beats.values())} calls outside the day's main beat" + \
                                (f" ({name.beat_name})." if name and name.beat_name else ".")
    return f


def _together(calls: dict[str, list[SalesCall]], rules: SalesRules) -> dict[str, tuple[str, float]]:
    """For each person: the other person whose calls are at the same place and time for most of their calls."""
    cell = rules.geo_together_m / 111_000 * 1.5          # degrees, a bit larger than the distance limit
    grid: dict[tuple[int, int], list[tuple[str, float, float, int]]] = defaultdict(list)
    for code, cs in calls.items():
        for c in cs:
            if c.lat is not None and c.start:
                grid[(int(c.lat / cell), int(c.lng / cell))].append((code, c.lat, c.lng, bizom.minutes_of(c.start)))
    out: dict[str, tuple[str, float]] = {}
    for code, cs in calls.items():
        mine = [c for c in cs if c.lat is not None and c.start]
        if len(mine) < rules.geo_together_min_calls:
            continue
        hits: Counter = Counter()
        for c in mine:
            t, gx, gy = bizom.minutes_of(c.start), int(c.lat / cell), int(c.lng / cell)
            seen = set()
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    for other, la, lo, ot in grid.get((gx + dx, gy + dy), ()):
                        if other != code and other not in seen and abs(ot - t) <= rules.geo_together_minutes \
                                and km((c.lat, c.lng), (la, lo)) * 1000 <= rules.geo_together_m:
                            seen.add(other)
            hits.update(seen)
        if hits:
            other, n = hits.most_common(1)[0]
            if n / len(mine) >= rules.geo_together_share:
                out[code] = (other, n / len(mine))
    return out


# ---------------------------------------------------------------- who may see what
def visible_codes(session: Session, principal) -> set[str] | None:
    """None = everyone (HR / admin: can upload or change settings). Others see the people whose team head, ASM, zonal
    head or HOD has their login's email."""
    from database.models.security import AppUser
    from security.permissions import Perm
    if Perm.UPLOAD_AND_SEND in principal.permissions or Perm.MANAGE_SETTINGS in principal.permissions:
        return None
    user = session.get(AppUser, principal.user_id)
    email = ((user.email if user else "") or "").strip().lower()
    if not email:
        return set()
    out = set()
    for e in session.scalars(select(SalesEmployee)):
        if email in {(x or "").strip().lower() for x in (e.manager_email, e.asm_email, e.zonal_email, e.hod_email)}:
            out.add(e.code)
    return out


# ---------------------------------------------------------------- day map + cases
def _labels(r: SalesEmployeeDay) -> list[dict]:
    ev = json.loads(r.geo_evidence or "{}")
    out = [{"code": k, "label": GEO[k][0], "level": GEO[k][1], "why": GEO[k][2], "evidence": ev.get(k, ""), "kind": "location"}
           for k in (r.geo_flags or "").split(",") if k in GEO]
    out += [{"code": k, "label": WARNINGS[k][0], "level": WARNINGS[k][1], "why": WARNINGS[k][2], "evidence": "", "kind": "day"}
            for k in (r.flags or "").split(",") if k in WARNINGS]
    return sorted(out, key=lambda x: (LEVEL[x["level"]], x["kind"] != "location"))


def day_map(session: Session, day: date, code: str) -> dict | None:
    up = session.scalar(select(SalesDayUpload).where(SalesDayUpload.report_date == day, SalesDayUpload.is_current.is_(True)))
    r = session.scalar(select(SalesEmployeeDay).where(SalesEmployeeDay.upload_id == up.upload_id, SalesEmployeeDay.code == code)) if up else None
    if r is None:
        r = _history_row(session, code, day)
        if r is None:
            return None
    rules = get_rules(session)
    locs = _locs(session, day)
    calls = _calls_by_code(session, day).get(code, [])
    outlets = {o.outlet_id: o for o in session.scalars(select(SalesOutlet).where(SalesOutlet.outlet_id.in_({c.outlet_id for c in calls if c.outlet_id})))}
    usual = usual_starts(session, day, rules).get(code)
    pts = lambda k: ({"lat": locs[(code, k)].lat, "lng": locs[(code, k)].lng, "time": locs[(code, k)].time} if (code, k) in locs else None)  # noqa: E731
    out_calls, prev = [], None
    for c in calls:
        o = outlets.get(c.outlet_id or "")
        leg = None
        if prev is not None and prev.lat is not None and c.lat is not None and prev.end and c.start:
            d = km((prev.lat, prev.lng), (c.lat, c.lng))
            mins = max(1, bizom.minutes_of(c.start) - bizom.minutes_of(prev.end))
            leg = {"km": round(d, 2), "minutes": mins, "kmh": round(d / (mins / 60), 1)}
        out_calls.append({"seq": c.seq, "start": c.start, "end": c.end, "duration_s": c.duration_s, "lat": c.lat, "lng": c.lng,
                          "outlet": o.name if o else c.outlet_id, "outlet_lat": o.lat if o else None, "outlet_lng": o.lng if o else None,
                          "beat": o.beat_name if o else None, "distance_m": c.distance_m, "productive": c.productive,
                          "away": c.distance_m is not None and c.distance_m > rules.geo_away_outlet_m, "leg": leg,
                          "fast": bool(leg and leg["km"] > 1 and leg["kmh"] > rules.max_speed_kmh)})
        prev = c
    case = session.scalar(select(SalesCase).where(SalesCase.code == code, SalesCase.day == day))
    from sales import photos
    return {"photos": photos.for_day(session, code, day), "date": day.isoformat(), "code": code, "name": r.name, "designation": r.designation or "", "manager": r.manager_name or "",
            "hod": r.hod_name or "", "status": r.status, "attendance_time": r.attendance_time, "eod_time": r.eod_time, "km": r.km,
            "market_minutes": r.market_minutes, "photo_url": r.photo_url, "attendance": pts("ATT"), "day_end": pts("EOD"),
            "usual_start": {"lat": usual[0], "lng": usual[1], "days": usual[2], "limit_km": round(usual[3], 1)} if usual else None, "calls": out_calls,
            "signs": _labels(r), "case": case_dict(case, code, day)}


def _history_row(session: Session, code: str, day: date) -> SalesEmployeeDay | None:
    """A stand-in day row for a day known only from the history file / a selfie (no full daily upload)."""
    h = session.scalar(select(SalesHistoryDay).where(SalesHistoryDay.code == code, SalesHistoryDay.day == day))
    e = session.scalar(select(SalesEmployee).where(SalesEmployee.code == code))
    from database.models.sales import SalesPhoto
    p = session.scalar(select(SalesPhoto).where(SalesPhoto.code == code, SalesPhoto.day == day).limit(1))
    if h is None and p is None:
        return None
    st = {"present": "PRESENT", "late": "LATE", "halfday": "HALF_DAY", "absent": "ABSENT", "leave": "LEAVE", "week_off": "WEEK_OFF",
          "not_marked": "ABSENT"}.get(h.status if h else "", "ABSENT")
    att = session.scalar(select(SalesLocation).where(SalesLocation.code == code, SalesLocation.day == day, SalesLocation.kind == "ATT"))
    return SalesEmployeeDay(code=code, name=(e.name if e else code), photo_url=p.url if p else None, designation=e.designation if e else None,
                            manager_name=e.manager_name if e else None, hod_name=e.hod_name if e else None, status=st,
                            attendance_time=att.time if att else None, km=None, market_minutes=None)


def case_dict(c: SalesCase | None, code: str, day: date) -> dict:
    return {"code": code, "date": day.isoformat(), "status": c.status if c else OPEN, "status_label": CASE_LABEL[c.status if c else OPEN],
            "note": c.note if c else "", "reviewed_by": c.reviewed_by if c else None, "reviewed_at": utc_iso(c.reviewed_at) if c else None}


def cases(session: Session, start: date, end: date, visible: set[str] | None, status: str = "", hod: str = "",
          kind: str = "") -> list[dict]:
    """People-days to check: location signs (kind 'location'), flagged selfies ('photos') or both ('')."""
    q = (select(SalesDayUpload.report_date, SalesEmployeeDay).join(SalesDayUpload, SalesDayUpload.upload_id == SalesEmployeeDay.upload_id)
         .where(SalesDayUpload.is_current.is_(True), SalesDayUpload.report_date >= start, SalesDayUpload.report_date <= end,
                SalesEmployeeDay.geo_flags.is_not(None)))
    reviews = {(c.code, c.day): c for c in session.scalars(select(SalesCase).where(SalesCase.day >= start, SalesCase.day <= end))}
    from sales import photos as photos_mod
    photo_days = photos_mod.flagged_days(session, start, end)
    staff = {e.code: e for e in session.scalars(select(SalesEmployee))}
    rows: dict[tuple[str, date], SalesEmployeeDay | None] = {(r.code, d): r for d, r in session.execute(q)}
    for key in photo_days:
        rows.setdefault(key, None)
    out = []
    for (code, d), r in rows.items():
        if visible is not None and code not in visible:
            continue
        e = staff.get(code)
        ph = photo_days.get((code, d), [])
        name = r.name if r else (e.name if e else code)
        hod_name = (r.hod_name if r else (e.hod_name if e else "")) or ""
        if hod and hod_name != hod:
            continue
        c = case_dict(reviews.get((code, d)), code, d)
        if status and c["status"] != status:
            continue
        if kind == "location" and not (r and r.geo_flags) or kind == "photos" and not ph:
            continue
        signs = _labels(r) if r else []
        psigns = {}
        for x in ph:
            for s in photos_mod.labels(x):
                psigns.setdefault(s["code"], s)
        out.append({"date": d.isoformat(), "code": code, "name": name, "designation": (r.designation if r else (e.designation if e else "")) or "",
                    "manager": (r.manager_name if r else (e.manager_name if e else "")) or "", "hod": hod_name,
                    "signs": [s for s in signs if s["kind"] == "location"], "photo_signs": list(psigns.values()),
                    "other_signs": [s["label"] for s in signs if s["kind"] == "day"],
                    "high": sum(1 for s in signs + list(psigns.values()) if s["level"] == "high"), "case": c})
    out.sort(key=lambda x: (x["case"]["status"] != OPEN, -x["high"], -len(x["signs"]) - len(x["photo_signs"]),
                            x["date"], x["name"]))
    return out


def review(session: Session, code: str, day: date, status: str, note: str | None, actor: str) -> dict:
    if status not in CASE_LABEL:
        raise ValueError("Status must be OPEN, OK or ACTION.")
    c = session.scalar(select(SalesCase).where(SalesCase.code == code, SalesCase.day == day)) or SalesCase(code=code, day=day)
    c.status, c.note, c.reviewed_by, c.reviewed_at = status, (note or "").strip()[:1000] or None, actor, now_utc()
    session.add(c)
    session.flush()
    return case_dict(c, code, day)


def summary(session: Session, day: date) -> dict:
    up = session.scalar(select(SalesDayUpload).where(SalesDayUpload.report_date == day, SalesDayUpload.is_current.is_(True)))
    if up is None:
        return {}
    c: Counter = Counter()
    people = 0
    for (g,) in session.execute(select(SalesEmployeeDay.geo_flags).where(SalesEmployeeDay.upload_id == up.upload_id,
                                                                          SalesEmployeeDay.geo_flags.is_not(None))):
        people += 1
        c.update(g.split(","))
    return {"people": people, "signs": [{"code": k, "label": GEO[k][0], "level": GEO[k][1], "n": n}
                                        for k, n in sorted(c.items(), key=lambda kv: (LEVEL[GEO[kv[0]][1]], -kv[1])) if k in GEO],
            "points": session.scalar(select(SalesLocation.id).where(SalesLocation.day == day).limit(1)) is not None,
            "calls": session.scalar(select(SalesCall.id).where(SalesCall.day == day).limit(1)) is not None}

