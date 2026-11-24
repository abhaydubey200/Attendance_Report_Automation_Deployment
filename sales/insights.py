"""Field Sales insights pack: the last 30 uploaded days for the people one report covers - the data behind the trend chart,
each person's 30-day strip and usual start time, the team-head scorecards and the weekday heatmap (dashboard, Excel and
HR Portal). Everything is counted from the stored days (Bizom's file + the app's absent / week-off / holiday rows); week
offs and holidays are never counted as absent."""

from __future__ import annotations

import statistics
from collections import Counter, defaultdict
from datetime import date

from sqlalchemy.orm import Session

from sales import patterns

CODE = {"PRESENT": "P", "LATE": "L", "HALF_DAY": "H", "ABSENT": "A", "LEAVE": "V", "WEEK_OFF": "O"}
WORKED = ("PRESENT", "LATE", "HALF_DAY")
WEEKDAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")


def pct(c: Counter) -> float | None:
    """Attendance % the same way everywhere: (present + late + half of half days) / (all - week off / holiday)."""
    due = sum(c.values()) - c["WEEK_OFF"]
    return round(100 * (c["PRESENT"] + c["LATE"] + 0.5 * c["HALF_DAY"]) / due, 1) if due else None


def _mins(hhmm: str | None) -> int | None:
    try:
        h, m = (hhmm or "").split(":")[:2]
        return int(h) * 60 + int(m)
    except ValueError:
        return None


def _hm(m: float | None) -> str:
    if m is None:
        return ""
    m = int(round(m))
    return f"{(m // 60) % 12 or 12}:{m % 60:02d} {'AM' if m < 720 else 'PM'}"


def pack(session: Session, day: date, codes: set[str] | None, team_of: dict[str, str], n_days: int = 30) -> dict:
    """team_of: code -> team head (from the report's own rows). Returns days, trend, per-person strips, team scorecard
    numbers and the weekday heatmap."""
    hist = patterns.history(session, day, codes, days_back=95)
    all_days = sorted({x.d for v in hist.values() for x in v})
    # Sundays / holidays: most people are off, and the few who work would show ~100% - left out of every % (kept in the strips)
    tot: dict[date, Counter] = defaultdict(Counter)
    for v in hist.values():
        for x in v:
            tot[x.d][x.status] += 1
    off_days = {d for d, c in tot.items() if c["WEEK_OFF"] > 0.5 * sum(c.values())}
    last = all_days[-n_days:]
    idx = {d: i for i, d in enumerate(last)}
    by_day: dict[date, Counter] = defaultdict(Counter)
    people = {}
    for code, days in hist.items():
        strip = ["-"] * len(last)
        c30: Counter = Counter()
        att = []
        mk = []
        for x in days:
            if x.d in idx:
                strip[idx[x.d]] = CODE.get(x.status, "-")
                by_day[x.d][x.status] += 1
                if x.d not in off_days:
                    c30[x.status] += 1
                if x.status in WORKED and x.market is not None:
                    mk.append(x.market)
            if x.status in WORKED and (m := _mins(x.att)) is not None:
                att.append(m)
        usual = statistics.median(att) if len(att) >= 5 else None
        people[code] = {"strip": "".join(strip), "pct30": pct(c30), "late30": c30["LATE"], "absent30": c30["ABSENT"],
                        "leave30": c30["LEAVE"], "worked30": sum(c30[s] for s in WORKED),
                        "usual_start": _hm(usual), "usual_start_min": usual, "avg_market": round(sum(mk) / len(mk)) if mk else None}
    trend = [{"date": d.isoformat(), "label": f"{d.day}-{d:%b}", "weekday": WEEKDAYS[d.weekday()],
              "pct": None if d in off_days else pct(by_day[d]), "off_day": d in off_days,
              "absent": by_day[d]["ABSENT"], "late": by_day[d]["LATE"], "off": by_day[d]["WEEK_OFF"],
              "people": sum(by_day[d].values())} for d in last]
    # team heads: last 30 days and a 12-week weekday heatmap
    team30: dict[str, Counter] = defaultdict(Counter)
    heat: dict[str, list[Counter]] = defaultdict(lambda: [Counter() for _ in range(7)])
    for code, days in hist.items():
        th = team_of.get(code)
        if not th:
            continue
        for x in days:
            if x.d in off_days:
                continue
            if x.d in idx:
                team30[th][x.status] += 1
            if (day - x.d).days < 84:
                heat[th][x.d.weekday()][x.status] += 1
    teams = {th: {"pct30": pct(c), "late30_pct": round(100 * c["LATE"] / max(1, sum(c[s] for s in WORKED)), 1),
                  "absent30": c["ABSENT"], "heat": [pct(w) for w in heat[th]]} for th, c in team30.items()}
    all_heat = [Counter() for _ in range(7)]
    for ws in heat.values():
        for i, w in enumerate(ws):
            all_heat[i].update(w)
    return {"off_days": sorted(d.isoformat() for d in off_days if d in idx), "days": [d.isoformat() for d in last], "labels": [f"{d.day}-{d:%b}" for d in last],
            "weekday_of": [WEEKDAYS[d.weekday()] for d in last], "trend": trend, "people": people, "teams": teams,
            "heat_all": [pct(w) for w in all_heat], "weekdays": list(WEEKDAYS)}


def scorecards(people: list[dict], pk: dict, trend4: list[dict]) -> list[dict]:
    """One row per team head: today's numbers from the report's people + 30-day numbers and the 4-week change."""
    by: dict[str, list[dict]] = defaultdict(list)
    for p in people:
        by[p["manager"] or "No team head"].append(p)
    t4 = {t["team_head"]: t for t in trend4}
    out = []
    for th, ps in by.items():
        c = Counter(p["status"] for p in ps)
        ranked = sorted((p for p in ps if (pk["people"].get(p["code"]) or {}).get("pct30") is not None),
                        key=lambda p: (pk["people"][p["code"]]["pct30"], p["name"]))
        t = pk["teams"].get(th, {})
        out.append({"team_head": th, "people": len(ps), "pct": pct(c), "absent": c["ABSENT"], "late": c["LATE"],
                    "signs": sum(1 for p in ps if p["flags"] or p.get("checks")), "patterns": sum(1 for p in ps if p.get("patterns")),
                    "pct30": t.get("pct30"), "late30_pct": t.get("late30_pct"), "absent30": t.get("absent30", 0),
                    "change4": (t4.get(th) or {}).get("change"), "heat": t.get("heat", [None] * 7),
                    "lowest": [f"{p['name']} ({pk['people'][p['code']]['pct30']:g}%)" for p in ranked[:2]],
                    "best": [f"{p['name']} ({pk['people'][p['code']]['pct30']:g}%)" for p in ranked[::-1][:2]]})
    out.sort(key=lambda r: (r["pct30"] if r["pct30"] is not None else 999, r["team_head"]))
    return out
