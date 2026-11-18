"""Month-end insights: the patterns a manager would otherwise have to dig out of a calendar by hand.

Everything here works on one recipient's people (their team, an HOD's people, or the company for the Director)
and the month's uploaded days. The same rules run in the interactive dashboard (JavaScript) for any period the
viewer picks; this module feeds the email, the Excel workbook and the dashboard's opening view.

Wording rules (emails): dates, never "today"; "your team"; employee names are fine, HOD / team / manager names are not.
"""

from __future__ import annotations

from collections import Counter
from datetime import date

from daily import analysis, reports

WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
TARGET = 90.0                  # attendance % target shown on charts and in the takeaways
STREAK_DAYS = 3                # absent on this many report days in a row = streak
MOVE_PTS = 5.0                 # attendance change vs last month that counts as improved / declined


def _pct(rows: list[dict], rules) -> float | None:
    return reports._tally(rows, rules)["attendance_pct"] if rows else None


def weekday_stats(codes: list[str], days: list[date], by_code: dict, rules) -> list[dict]:
    out = []
    for i, name in enumerate(WEEKDAYS):
        ds = [d for d in days if d.weekday() == i]
        rows = [r for d in ds for c in codes if (r := by_code.get(c, {}).get(d))]
        if not rows:
            continue
        t = reports._tally(rows, rules)
        if t["tracked"] < 0.2 * len(rows):          # Sundays / weekly off: almost nobody due -> not compared
            continue
        out.append({"day": name, "days": len(ds), "attendance_pct": t["attendance_pct"], "absent": t["absent"], "late": t["late"],
                    "missing_punch": t["missing_punch"]})
    return out


def week_stats(codes: list[str], days: list[date], by_code: dict, rules) -> list[dict]:
    weeks: dict[tuple, list[date]] = {}
    for d in days:
        weeks.setdefault(d.isocalendar()[:2], []).append(d)
    out = []
    for n, ds in enumerate(weeks.values(), start=1):
        rows = [r for d in ds for c in codes if (r := by_code.get(c, {}).get(d))]
        t = reports._tally(rows, rules)
        out.append({"week": f"Week {n}", "range": f"{ds[0]:%d %b} – {ds[-1]:%d %b}", "days": len(ds), "attendance_pct": t["attendance_pct"],
                    "absent": t["absent"], "late": t["late"], "missing_punch": t["missing_punch"]})
    return out


def streaks(people: list[dict], days: list[date], by_code: dict) -> list[dict]:
    """People absent on STREAK_DAYS or more report days in a row (their longest run)."""
    out = []
    for p in people:
        per = by_code.get(p["code"].upper(), {})
        best, run, start, best_span = 0, 0, None, None
        for d in days:
            r = per.get(d)
            if r is None or r["status"] in ("WEEK_OFF", "HOLIDAY", "NOT_TRACKED"):
                continue                                    # no record / week off does not break or extend a run
            if r["status"] == "ABSENT":
                run += 1
                start = start or d
                if run > best:
                    best, best_span = run, (start, d)
            else:
                run, start = 0, None
        if best >= STREAK_DAYS:
            out.append({"code": p["code"], "name": p["name"], "days": best, "from": best_span[0], "to": best_span[1]})
    return sorted(out, key=lambda x: (-x["days"], x["name"]))


def monday_friday(people: list[dict], days: list[date], by_code: dict) -> list[dict]:
    """People whose absences cluster next to the weekend (2+ on Mondays / Fridays, at least half of their absences)."""
    out = []
    for p in people:
        per = by_code.get(p["code"].upper(), {})
        absent = [d for d in days if (r := per.get(d)) and r["status"] == "ABSENT"]
        mf = [d for d in absent if d.weekday() in (0, 4)]
        if len(mf) >= 2 and len(mf) * 2 >= len(absent):
            out.append({"code": p["code"], "name": p["name"], "mon_fri": len(mf), "absent": len(absent)})
    return sorted(out, key=lambda x: (-x["mon_fri"], x["name"]))


def perfect(people: list[dict]) -> list[dict]:
    """Present (or on duty / WFH) every tracked day: no absence, leave, late arrival, missing punch or early leaving."""
    return sorted([p for p in people if p["tracked"] and not (p["absent"] or p["late"] or p["missing_punch"] or p["leave"]
                                                              or p["half_day"] or p.get("left_early"))],
                  key=lambda p: p["name"])


def movers(people: list[dict], prev: dict[str, dict] | None) -> tuple[list[dict], list[dict]]:
    """(improved, declined) by attendance % vs the previous month, MOVE_PTS points or more."""
    if not prev:
        return [], []
    up, down = [], []
    for p in people:
        b = prev.get(p["code"].upper())
        if not b or b.get("attendance_pct") is None or p["attendance_pct"] is None:
            continue
        d = round(p["attendance_pct"] - b["attendance_pct"], 1)
        row = {"code": p["code"], "name": p["name"], "now": p["attendance_pct"], "before": b["attendance_pct"], "change": d}
        if d >= MOVE_PTS:
            up.append(row)
        elif d <= -MOVE_PTS:
            down.append(row)
    return sorted(up, key=lambda x: -x["change"]), sorted(down, key=lambda x: x["change"])


def leave_mix(codes: list[str], days: list[date], by_code: dict) -> list[dict]:
    c = Counter((r.get("leave_type") or "Leave") for code in codes for d in days
                if (r := by_code.get(code, {}).get(d)) and r["status"] in ("LEAVE", "HALF_DAY"))
    return [{"type": k, "days": v} for k, v in c.most_common()]


def build(people: list[dict], days: list[date], by_code: dict, rules, totals: dict, prev_totals: dict | None,
          prev_people: dict[str, dict] | None, who: str = "your team") -> dict:
    """All month insights + plain-language takeaways (most important first). kind: good | warn | bad | info."""
    codes = [p["code"].upper() for p in people]
    wd, wk = weekday_stats(codes, days, by_code, rules), week_stats(codes, days, by_code, rules)
    st, mf, pf = streaks(people, days, by_code), monday_friday(people, days, by_code), perfect(people)
    up, down = movers(people, prev_people)
    lm = leave_mix(codes, days, by_code)
    take: list[dict] = []
    pct = totals.get("attendance_pct")
    if pct is not None:
        vs = ""
        if prev_totals and prev_totals.get("attendance_pct") is not None:
            d = round(pct - prev_totals["attendance_pct"], 1)
            vs = " (same as last month)" if d == 0 else f" ({'up' if d > 0 else 'down'} {abs(d):g} pts on last month)"
        gap = round(pct - TARGET, 1)
        take.append({"kind": "good" if gap >= 0 else "warn" if gap > -10 else "bad", "view": "trends",
                     "text": f"Average attendance was {pct:g}%{vs} - " + (f"{gap:g} pts above" if gap >= 0 else f"{abs(gap):g} pts below")
                             + f" the {TARGET:g}% target."})
    tw = [w for w in wd if w["attendance_pct"] is not None and w["days"] >= 2]
    if len(tw) >= 3:
        lo, hi = min(tw, key=lambda w: w["attendance_pct"]), max(tw, key=lambda w: w["attendance_pct"])
        if hi["attendance_pct"] - lo["attendance_pct"] >= 3:
            take.append({"kind": "warn", "view": "weekday",
                         "text": f"{lo['day']}s had the lowest attendance ({lo['attendance_pct']:g}%), {hi['day']}s the highest "
                                 f"({hi['attendance_pct']:g}%). Plan meetings and deadlines away from {lo['day']}s."})
    tk = [w for w in wk if w["attendance_pct"] is not None and w["days"] >= 3]
    if len(tk) >= 2:
        lo = min(tk, key=lambda w: w["attendance_pct"])
        take.append({"kind": "info", "view": "weeks",
                     "text": f"The weakest week was {lo['range']} at {lo['attendance_pct']:g}% ({lo['absent']} absence days)."})
    absences = sorted(((p["absent"], p["name"]) for p in people if p["absent"]), key=lambda x: (-x[0], x[1]))   # ties: by name (as the dashboard)
    total_abs = sum(a for a, _ in absences)
    if total_abs >= 5 and len(absences) >= 4:
        top = absences[:3]
        share = round(100 * sum(a for a, _ in top) / total_abs)
        if share >= 40:
            take.append({"kind": "warn", "view": "people:absent",
                         "text": f"{share}% of all absence days came from 3 people ({', '.join(n for _, n in top)}). "
                                 f"A conversation with them moves the number most."})
    if st:
        names = ", ".join(f"{s['name']} ({s['days']} days)" for s in st[:4])
        take.append({"kind": "bad", "view": "people:streak",
                     "text": f"{len(st)} {'person was' if len(st) == 1 else 'people were'} absent {STREAK_DAYS}+ report days in a row: {names}."})
    if mf:
        take.append({"kind": "warn", "view": "people:monfri",
                     "text": f"{len(mf)} {'person has' if len(mf) == 1 else 'people have'} absences clustered on Mondays / Fridays "
                             f"({', '.join(m['name'] for m in mf[:4])}) - check for a long-weekend pattern."})
    if totals.get("missing_punch"):
        n = sum(1 for p in people if p["missing_punch"])
        take.append({"kind": "warn", "view": "people:mp",
                     "text": f"{totals['missing_punch']} missing punches across {n} {'person' if n == 1 else 'people'} - "
                             f"get them regularised in Pocket HRMS before payroll."})
    if totals.get("late"):
        n = sum(1 for p in people if p["late"])
        take.append({"kind": "warn", "view": "people:late",
                     "text": f"{totals['late']} late arrivals by {n} {'person' if n == 1 else 'people'}; average arrival "
                             f"{analysis.t12(totals.get('avg_in_time')) or '-'}."})
    if down:
        take.append({"kind": "bad", "view": "people:declined",
                     "text": f"{len(down)} {'person' if len(down) == 1 else 'people'} slipped {MOVE_PTS:g}+ pts on last month: "
                             + ", ".join(f"{d['name']} ({d['before']:g}% → {d['now']:g}%)" for d in down[:3]) + "."})
    if up:
        take.append({"kind": "good", "view": "people:improved",
                     "text": f"{len(up)} {'person' if len(up) == 1 else 'people'} improved {MOVE_PTS:g}+ pts: "
                             + ", ".join(f"{u['name']} ({u['before']:g}% → {u['now']:g}%)" for u in up[:3]) + "."})
    if pf:
        take.append({"kind": "good", "view": "people:perfect",
                     "text": f"{len(pf)} {'person had' if len(pf) == 1 else 'people had'} perfect attendance (no absence, leave, "
                             f"late arrival or missing punch) - worth a word of recognition."})
    if lm:
        take.append({"kind": "info", "view": "trends",
                     "text": "Leave taken: " + ", ".join(f"{x['type']} {x['days']}" for x in lm[:5]) + " day(s)."})
    return {"weekday": wd, "weeks": wk, "streaks": st, "monday_friday": mf, "perfect": pf, "improved": up, "declined": down,
            "leave_mix": lm, "takeaways": take, "target": TARGET}
