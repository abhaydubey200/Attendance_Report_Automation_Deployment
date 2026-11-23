"""Field Sales daily report: one 'view' of the day for a recipient, rendered as the email, the Excel workbook and the
interactive dashboard (same look as Module 1). Wording: the date, never "today"; "needs checking", never "fraud"."""

from __future__ import annotations

import io
import json
import re
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

import xlsxwriter
from jinja2 import ChoiceLoader, Environment, FileSystemLoader, select_autoescape

from daily.analysis import t12
from daily.branding import excel_banner, logo_data_uri
from sales.analysis import STATUS_LABEL, WARNINGS, WORKING

_HERE = Path(__file__).parent
_env = Environment(loader=ChoiceLoader([FileSystemLoader(_HERE / "templates"), FileSystemLoader(_HERE.parent / "daily" / "templates")]),
                   autoescape=select_autoescape(["html"]))
TITLES = {"team": "Daily Field Sales Attendance", "company": "Daily Field Sales Attendance – Company",
          "hr": "Daily Field Sales – HR Action List"}
COLORS = {"PRESENT": "#16a34a", "LATE": "#d97706", "HALF_DAY": "#f59e0b", "LEAVE": "#64748b", "WEEK_OFF": "#cbd5e1", "ABSENT": "#dc2626"}


def pct_of(rows) -> float | None:
    c = Counter(r.status for r in rows)
    due = len(rows) - c["WEEK_OFF"]
    return round(100 * (c["PRESENT"] + c["LATE"] + 0.5 * c["HALF_DAY"]) / due, 1) if due else None


def hm(minutes: int | None) -> str:
    return "" if minutes is None else f"{minutes // 60}:{minutes % 60:02d}"


def manager_label(name: str | None) -> str:
    """'Vacant_TSM_Rajasthan-2' -> 'Vacant (TSM Rajasthan-2)'."""
    n = (name or "").strip()
    if n.lower().startswith("vacant"):
        rest = n[6:].strip("_ -").replace("_", " ")
        return f"Vacant ({rest})" if rest else "Vacant"
    return n


def _mins(hhmm: str | None) -> int | None:
    try:
        h, m = (hhmm or "").split(":")[:2]
        return int(h) * 60 + int(m)
    except ValueError:
        return None


def _person(r) -> dict:
    flags = [f for f in (r.flags or "").split(",") if f]
    return {"code": r.code, "name": r.name, "designation": r.designation or "", "zone": r.zone or "", "manager": manager_label(r.manager_name),
            "zonal": r.zonal_name or "", "hod": r.hod_name or "", "status": r.status, "status_label": STATUS_LABEL.get(r.status, r.status),
            "not_marked": r.status == "ABSENT" and not r.bizom_status, "leave": r.leave_type or "",
            "att": t12(r.attendance_time) or "", "first": t12(r.first_activity) or "", "last": t12(r.last_activity) or "",
            "market": hm(r.market_minutes), "market_min": r.market_minutes, "km": r.km, "eod": t12(r.eod_time) or "",
            "att_min": _mins(r.attendance_time), "eod_min": _mins(r.eod_time),
            "calls": r.calls, "productive": r.productive_calls, "short_calls": r.short_calls, "far_calls": r.far_calls,
            "order_value": r.order_value, "in_master": r.in_master,
            "flags": [{"code": f, "label": WARNINGS[f][0], "level": WARNINGS[f][1], "why": WARNINGS[f][2]} for f in flags if f in WARNINGS],
            "evidence": _evidence(r, flags)}


def _evidence(r, flags: list[str]) -> str:
    bits = []
    if "NO_ACTIVITY" in flags:
        bits.append(f"marked {t12(r.attendance_time) or '-'}, no activity")
    if {"VERY_SHORT_MARKET", "SHORT_MARKET"} & set(flags):
        bits.append(f"{hm(r.market_minutes)} h in market")
    if "LATE_START" in flags:
        bits.append(f"marked {t12(r.attendance_time)}, first activity {t12(r.first_activity)}")
    if "HIGH_KM" in flags or "ZERO_KM" in flags:
        bits.append(f"{r.km:g} km")
    if "FAR_ATTENDANCE" in flags and r.attendance_variance_m is not None:
        bits.append(f"marked {r.attendance_variance_m:g} m away")
    if "SHORT_CALLS" in flags:
        bits.append(f"{r.short_calls} of {r.calls} visits under a minute")
    if "FAR_CALLS" in flags:
        bits.append(f"{r.far_calls} visit(s) away from the outlet (up to {r.max_call_distance_m:g} m)")
    if "FAST_MOVES" in flags:
        bits.append(f"{r.fast_moves} impossible move(s) between visits")
    if "DAY_NOT_CLOSED" in flags:
        bits.append("day closed automatically at 11:59 PM")
    if "SHORT_DAY" in flags:
        bits.append(f"marked {t12(r.attendance_time)}, day ended {t12(r.eod_time)}")
    if "BEAT_JUMP" in flags:
        bits.append(f"{r.beat_jump_calls} visits outside the beat")
    return "; ".join(bits)


def build_view(rows, day: dict, view: str, recipient: str, d: date, checks: list[dict] | None = None,
               proof: list[dict] | None = None, ctx: dict | None = None) -> dict:
    people = [_person(r) for r in sorted(rows, key=lambda r: r.name)]
    cnt = Counter(p["status"] for p in people)
    flagged = sorted([p for p in people if p["flags"]],
                     key=lambda p: (-sum(f["level"] == "high" for f in p["flags"]), -len(p["flags"]), p["name"]))
    warn = Counter(f["code"] for p in people for f in p["flags"])
    teams = []
    if view != "team":
        g = defaultdict(list)
        for r in rows:
            g[(r.hod_name or "No HOD", r.zonal_name or "No zonal head")].append(r)
        for (hod, zonal), rs in sorted(g.items(), key=lambda kv: (pct_of(kv[1]) if pct_of(kv[1]) is not None else 999, kv[0])):
            c = Counter(r.status for r in rs)
            teams.append({"hod": hod, "zonal": zonal, "people": len(rs), "pct": pct_of(rs), "absent": c["ABSENT"],
                          "late": c["LATE"], "flagged": sum(1 for r in rs if r.flags)})
    safe = "".join(ch if ch.isalnum() else "_" for ch in recipient).strip("_")
    out = {
        "view": view, "title": TITLES[view], "recipient": recipient, "date": d, "date_long": f"{d:%d-%b-%Y}", "weekday": f"{d:%A}",
        "people": people, "n": len(people), "counts": {k: cnt.get(k, 0) for k in STATUS_LABEL}, "pct": pct_of(rows),
        "not_marked": [p for p in people if p["status"] == "ABSENT"], "late": [p for p in people if p["status"] == "LATE"],
        "flagged": flagged, "flagged_high": sum(1 for p in flagged if any(f["level"] == "high" for f in p["flags"])),
        "warnings": [{"code": k, "label": WARNINGS[k][0], "level": WARNINGS[k][1], "why": WARNINGS[k][2], "n": warn[k]}
                     for k in WARNINGS if warn.get(k)],
        "teams": teams, "data": day.get("data", {}) if view == "hr" else {}, "files": day.get("files", {}),
        "working": sum(cnt.get(k, 0) for k in WORKING), "colors": COLORS, "status_label": STATUS_LABEL,
        "stem": f"Field_Sales_{d.isoformat()}_{safe}",
        "checks": checks or [], "checks_summary": _checks_summary(checks or []),
        "checks_high": sum(1 for c in (checks or []) if c["level"] == "high"),
        "proof": proof or [],
        "ctx": ctx or {}, "company_pct": day.get("attendance_pct"),
        "off_day": day.get("off_day"),
        "state_holidays": day.get("state_holidays") or {},
    }
    pat = (ctx or {}).get("patterns") or {}
    lv = ("high", "medium", "low")
    out["patterns"] = sorted([{"code": p["code"], "name": p["name"], "designation": p["designation"], "manager": p["manager"],
                               "status_label": p["status_label"], "patterns": pat[p["code"]]} for p in people if p["code"] in pat],
                             key=lambda x: (lv.index(x["patterns"][0]["level"]), -len(x["patterns"]), x["name"]))
    by_check = {c["code"]: c["signs"] for c in (checks or [])}
    for p in people:
        p["patterns"] = pat.get(p["code"], [])
        p["checks"] = [{"kind": s["kind"], "label": s["label"], "level": s["level"], "why": s["why"]} for s in by_check.get(p["code"], [])]
        p["risk"] = next((c["risk"] for c in (checks or []) if c["code"] == p["code"]), None)
        ai = ((ctx or {}).get("absent_info") or {}).get(p["code"])
        p["last_marked"], p["absent_streak"] = (ai or {}).get("last_marked"), (ai or {}).get("streak")
    out["trend"] = _trend(out)
    out["highlights"] = highlights(out)
    return out


def _trend(v: dict) -> str:
    """'down 2.1 points on 17-Nov; company 85%' - empty when there is nothing to compare."""
    bits = []
    prev, now = v["ctx"].get("prev_pct"), v["pct"]
    if prev is not None and now is not None:
        diff = round(now - prev, 1)
        bits.append("same as" if diff == 0 else f"{'up' if diff > 0 else 'down'} {abs(diff):g} point{'s' if abs(diff) != 1 else ''} on")
        bits[-1] += f" {v['ctx']['prev_date']:%d-%b}"
    if v["view"] == "team" and v["company_pct"] is not None and now is not None:
        bits.append(f"company {v['company_pct']:g}%")
    return "; ".join(bits)


def highlights(v: dict) -> list[dict]:
    """At most six short lines for the email; every list and the proof are in the dashboard and Excel."""
    h: list[dict] = []
    c = v["counts"]
    if v.get("off_day"):
        h.append({"level": "low", "text": f"{v['off_day']}: people who did not mark attendance are counted as week off / holiday, "
                                          f"not absent ({c['PRESENT'] + c['LATE'] + c['HALF_DAY']} worked)."})
    sh = v.get("state_holidays") or {}
    if sh and not v.get("off_day"):
        h.append({"level": "low", "text": "State holiday (HR's holiday list): " + ", ".join(f"{n} ({k} people)" for n, k in sh.items())
                                          + " - not counted as absent."})
    if c["ABSENT"]:
        if v["view"] == "team":
            names = ", ".join(p["name"] for p in v["not_marked"][:5]) + (f" and {c['ABSENT'] - 5} more" if c["ABSENT"] > 5 else "")
            h.append({"level": "high", "text": f"{c['ABSENT']} absent: {names}."})
        else:
            low = next((t for t in v["teams"] if t["pct"] is not None), None)
            h.append({"level": "high", "text": f"{c['ABSENT']} absent" + (f"; lowest team {low['zonal']} ({low['pct']:g}%)." if low else ".")})
    pats = v.get("patterns") or []
    if pats:
        def short(x: dict) -> str:
            t = x["patterns"][0]["text"].split(":")[0].rstrip(".")
            return f"{x['name']} – {t[:1].lower()}{t[1:]}"
        h.append({"level": pats[0]["patterns"][0]["level"],
                  "text": f"Repeat patterns ({len(pats)}): " + "; ".join(short(x) for x in pats[:3])
                          + (f"; and {len(pats) - 3} more" if len(pats) > 3 else "") + ". Dates in the attachments."})
    tt = [t for t in (v["ctx"].get("team_trend") or []) if t["change"] is not None]
    if v["view"] != "team" and len(tt) > 1 and tt[0]["change"] <= -10:
        t = tt[0]
        h.append({"level": "medium", "text": f"Biggest drop: {t['team_head']}'s team ({t['people']} people) {t['weeks'][-1]:g}% in the week "
                                              f"{t['week_ranges'][-1]}, {t['before_avg']:g}% on average in the 3 weeks before."})
    streaks = v["ctx"].get("streaks") or []
    if streaks:
        h.append({"level": "high", "text": "Absent several days in a row: " +
                  ", ".join(f"{n} ({k} days)" for n, k in streaks[:4]) + (f" and {len(streaks) - 4} more." if len(streaks) > 4 else ".")})
    if c["LATE"]:
        h.append({"level": "medium", "text": f"{c['LATE']} late (after 10:30 AM)."})
    if v["flagged"]:
        top = "; ".join(f"{p['name']} – {p['flags'][0]['label'].lower()}" for p in v["flagged"][:2])
        h.append({"level": "high" if v["flagged_high"] else "medium",
                  "text": f"{len(v['flagged'])} need checking ({v['flagged_high']} serious): {top}" + (" and more." if len(v["flagged"]) > 2 else ".")})
    if v["checks"]:
        def reason(x: dict) -> str:
            s = x["signs"][0]
            # keep short proof like "(usual 84)", drop long notes; the full wording stays in the attachments
            short = re.sub(r"\s*\([^)]{25,}\)", "", s["why"] or "").split(". ")[0]
            why = ", ".join(w.strip().rstrip(".") for w in short.split(";")[:2] if w.strip())
            return f"{x['name']} (risk {x['risk']}) – {why[:1].lower() + why[1:] if why else s['label'].lower()}"
        top = "; ".join(reason(x) for x in v["checks"][:3])
        h.append({"level": v["checks"][0]["level"], "text": f"Highest risk: {top}."})
        reused = [x["name"] for x in v["checks"] if any(s["label"].startswith(("Selfie reused", "Same selfie")) for s in x["signs"])]
        if reused:
            h.append({"level": "high", "text": f"Selfie reused (confirmed by image comparison): {', '.join(reused[:4])}."})
    si = v["ctx"].get("staff_issues") or {}
    if v["view"] == "hr" and (si.get("possibly_left") or si.get("never_in_bizom") or si.get("doj_wrong")):
        h.append({"level": "medium", "text": f"Staff list to fix: {len(si.get('possibly_left', []))} possibly left (not in Bizom for "
                                              f"{si.get('working_days_checked')} working days), {len(si.get('never_in_bizom', []))} never mark "
                                              f"attendance in Bizom, {len(si.get('doj_wrong', []))} joining date looks wrong. Proof in the Excel."})
    if v["view"] == "hr" and v["data"] and (v["data"].get("not_in_staff_list") or v["data"].get("left_but_marked")):
        h.append({"level": "low", "text": f"Data to fix: {len(v['data'].get('not_in_staff_list', []))} not on the staff list, "
                                           f"{len(v['data'].get('left_but_marked', []))} marked attendance though Left."})
    return h[:6]


def _checks_summary(checks: list[dict]) -> list[dict]:
    from sales.checks import summary
    return summary(checks)


# ---------------------------------------------------------------- email
def email_html(v: dict) -> str:
    return _env.get_template("sales_mail.html").render(v=v)


def email_text(v: dict) -> str:
    c = v["counts"]
    lines = [f"Dear {v['recipient']},", "",
             f"Field sales attendance for {v['weekday']}, {v['date_long']}: {v['n']} people." + (f" ({v['trend']})" if v["trend"] else ""),
             f"Attendance {v['pct'] if v['pct'] is not None else '-'}% | Absent {c['ABSENT']} | Late {c['LATE']} | "
             f"Needs checking {len(v['flagged'])}" + (f" | Location & selfie checks {len(v['checks'])}" if v["checks"] else ""), ""]
    if v["highlights"]:
        lines += ["Highlights:"] + [f"- {x['text']}" for x in v["highlights"]] + [""]
    if v.get("feedback"):
        lines += ["Was this right? Your answer makes the checks more accurate:"] + [
            f"- {f['name']} ({f['sign'].lower()}): right {f['right']} | not right {f['wrong']}" for f in v["feedback"]] + [""]
    lines += ["Full lists, selfies and map links: the attached dashboard (open in Chrome or Edge) and Excel.",
              "Warning signs are for checking, not proof. Automated email from the APIS HR Portal (source: Bizom)."]
    return "\n".join(lines)


# ---------------------------------------------------------------- Excel
def excel(v: dict) -> bytes:
    """One workbook per email: a Summary, then one styled table per list (filter buttons, banded rows, frozen header).
    Columns nobody has data for are left out; every sheet says what it is in its title line."""
    buf = io.BytesIO()
    wb = xlsxwriter.Workbook(buf, {"in_memory": True, "strings_to_formulas": False, "strings_to_urls": False})
    head = wb.add_format({"bold": True, "font_color": "#FFFFFF", "bg_color": "#14213D", "text_wrap": True, "valign": "vcenter", "border": 1})
    cell = wb.add_format({"valign": "top"})
    wrap = wb.add_format({"valign": "top", "text_wrap": True})
    big = wb.add_format({"border": 1, "border_color": "#E6E8EF", "bold": True, "font_size": 13, "font_color": "#14213D", "align": "center"})
    bold = wb.add_format({"border": 1, "border_color": "#E6E8EF", "bold": True, "font_color": "#14213D"})
    note = wb.add_format({"italic": True, "font_color": "#5D6577", "text_wrap": True, "valign": "top"})
    lvl = {k: wb.add_format({"bold": True, "font_color": c, "bg_color": b, "valign": "top", "text_wrap": True})
           for k, c, b in (("high", "#B91C1C", "#FEF3F2"), ("medium", "#B45309", "#FFF8EB"), ("low", "#475569", "#F1F5F9"))}
    st = {k: wb.add_format({"bold": True, "font_color": c, "valign": "top"}) for k, c in COLORS.items()}
    pctf = {k: wb.add_format({"bold": True, "font_color": c, "num_format": "0.0", "valign": "top"})
            for k, c in (("good", "#15803D"), ("warn", "#B45309"), ("bad", "#B91C1C"))}
    neg = wb.add_format({"bold": True, "font_color": "#B91C1C", "num_format": "+0.0;-0.0;0", "valign": "top"})
    pos = wb.add_format({"font_color": "#15803D", "num_format": "+0.0;-0.0;0", "valign": "top"})

    def pfmt(x):
        return None if x in (None, "") else pctf["good" if x >= 90 else "warn" if x >= 75 else "bad"]

    def table(name: str, title: str, subtitle: str, cols: list[tuple[str, int]], rows: list[list], empty: str,
              fmt=None, freeze: int = 2, height: int | None = None, footnote: str | None = None):
        """cols: (header, width); fmt(i, j, value) -> a cell format or None (default: wrap text in wide columns)."""
        ws = wb.add_worksheet(name[:31])
        excel_banner(wb, ws, [w for _, w in cols], title, subtitle)
        for j, (_, w) in enumerate(cols):
            ws.set_column(j, j, w, wrap if w >= 30 else cell)
        top = 3
        if not rows:
            ws.write(top, 0, empty, note)
            return ws
        clean = [["" if x is None else x for x in r] for r in rows]
        ws.add_table(top, 0, top + len(clean), len(cols) - 1, {
            "data": clean, "style": "Table Style Light 15", "autofilter": True, "banded_rows": True,
            "columns": [{"header": h, "header_format": head} for h, _ in cols]})
        ws.set_row(top, 30)
        for i, r in enumerate(clean):
            if height:
                ws.set_row(top + 1 + i, height)
            for j, x in enumerate(r):
                f = fmt(i, j, x) if fmt else None
                if f is not None:
                    ws.write(top + 1 + i, j, x, f)
        if footnote:
            ws.write(top + len(clean) + 2, 0, footnote, note)
        ws.freeze_panes(top + 1, freeze)
        return ws

    # ---- Summary
    ws = wb.add_worksheet("Summary")
    excel_banner(wb, ws, [40, 14, 14, 14], f"Field sales attendance – {v['date_long']} ({v['weekday']})", v["recipient"])
    ws.set_column(0, 0, 44)
    ws.set_column(1, 3, 14)
    kpis = [("People", v["n"]), ("Attendance %", v["pct"] if v["pct"] is not None else "-")] + \
           [(v["status_label"][k], v["counts"][k]) for k in v["counts"]] + \
           [("Need checking", len(v["flagged"])), ("Need checking – serious", v["flagged_high"]),
            ("Repeat patterns (people)", len(v.get("patterns") or [])), ("Location & selfie checks (people)", len(v["checks"]))]
    r = 4
    ws.write(3, 0, "Figure", head)
    ws.write(3, 1, "Value", head)
    for i, (k, val) in enumerate(kpis, start=r):
        ws.write(i, 0, k, bold)
        ws.write(i, 1, val, big)
    r += len(kpis) + 1
    if v.get("trend"):
        ws.write(r, 0, f"Trend: {v['trend']}", note)
        r += 2
    if v["warnings"]:
        for j, h_ in enumerate(("Warning sign", "People", "Level")):
            ws.write(r, j, h_, head)
        for i, w in enumerate(v["warnings"], start=r + 1):
            ws.write(i, 0, w["label"], bold)
            ws.write(i, 1, w["n"], big)
            ws.write(i, 2, w["level"], lvl[w["level"]])
        r += 2 + len(v["warnings"])
    if v["highlights"]:
        ws.write(r, 0, "Highlights (as in the email)", head)
        for i, x in enumerate(v["highlights"], start=r + 1):
            ws.merge_range(i, 0, i, 3, x["text"], lvl[x["level"]])
            ws.set_row(i, 32)
        r += 2 + len(v["highlights"])
    ws.write(r, 0, "Warning signs are for checking with the person, not proof of anything. Each sheet has filter buttons in its header.", note)

    if v["teams"]:
        table("By team", f"By team – {v['date_long']}", "Lowest attendance first",
              [("HOD", 22), ("Zonal head", 24), ("People", 9), ("Attendance %", 12), ("Absent", 9), ("Late", 8), ("Need checking", 12)],
              [[t["hod"], t["zonal"], t["people"], t["pct"], t["absent"], t["late"], t["flagged"]] for t in v["teams"]], "No teams.",
              fmt=lambda i, j, x: pfmt(x) if j == 3 else None, freeze=1)

    table("Needs checking", f"Needs checking – {v['date_long']}", "Warning signs of the day, most serious first – for checking, not proof",
          [("Code", 10), ("Name", 26), ("Designation", 12), ("Manager", 22), ("Warning signs", 44), ("Evidence", 60)],
          [[p["code"], p["name"], p["designation"], p["manager"], "; ".join(f["label"] for f in p["flags"]), p["evidence"]] for p in v["flagged"]],
          "Nothing to check on this day.",
          fmt=lambda i, j, x: lvl[min((f["level"] for f in v["flagged"][i]["flags"]), key=("high", "medium", "low").index)] if j == 4 else None)

    if v.get("patterns"):
        prow, plv = [], []
        for x in v["patterns"]:
            for p in x["patterns"]:
                prow.append([x["code"], x["name"], x["designation"], x["manager"], x["status_label"], p["label"], p["text"]])
                plv.append(p["level"])
        table("Patterns", f"Repeat patterns – {v['date_long']}",
              "Counted over each person's own uploaded working days (week offs, leave, holidays and days without an upload are not counted)",
              [("Code", 10), ("Name", 26), ("Designation", 11), ("Manager", 22), ("On the day", 12), ("Pattern", 30), ("Proof (dates from Bizom)", 80)],
              prow, "", fmt=lambda i, j, x: lvl[plv[i]] if j == 5 else None)

    tt = v["ctx"].get("team_trend") or []
    if len(tt) > 1:
        table("Team heads - 4 weeks", f"Team heads – last 4 weeks to {v['date_long']}",
              "Attendance % per rolling week (7 days ending on the report day); week offs and holidays not counted; biggest drop first",
              [("Team head", 28), ("People", 8)] + [(rg, 13) for rg in tt[0]["week_ranges"]] + [("3 weeks before (avg)", 13), ("Change (points)", 11)],
              [[t["team_head"], t["people"], *t["weeks"], t["before_avg"], t["change"]] for t in tt], "",
              fmt=lambda i, j, x: (neg if isinstance(x, (int, float)) and x <= -10 else pos if isinstance(x, (int, float)) and x > 0 else None)
              if j == len(tt[0]["weeks"]) + 3 else pfmt(x) if 2 <= j < 2 + len(tt[0]["weeks"]) and isinstance(x, (int, float)) else None, freeze=1)

    if v["checks"]:
        crow, clv = [], []
        for c in v["checks"]:
            for s in c["signs"]:
                crow.append([c["risk"], c["code"], c["name"], c["designation"], c["manager"], s["kind"], s["label"], s["why"]])
                clv.append(s["level"])
        table("Location & selfie checks", f"Location & selfie checks – {v['date_long']}",
              "Highest risk first. Risk 0-100 = the day's signs weighted by how often each was right when HR checked; map and selfies in the HR Portal",
              [("Risk", 7), ("Code", 10), ("Name", 26), ("Designation", 11), ("Manager", 22), ("Type", 10), ("Warning sign", 32), ("Why", 70)],
              crow, "", fmt=lambda i, j, x: lvl[clv[i]] if j == 6 else None, freeze=3)

    if v["proof"]:
        wp = wb.add_worksheet("Proof")
        cols = [("Risk", 6), ("Employee", 24), ("Warning signs and why", 52), ("Attendance selfie", 17), ("Matching selfie", 17), ("Where", 30)]
        excel_banner(wb, wp, [w for _, w in cols], f"Proof – {v['date_long']}", "Selfies are small copies made for this workbook; click one to open the original on Bizom")
        link = wb.add_format({"font_color": "#1D4ED8", "underline": 1, "valign": "top", "text_wrap": True})
        top_ = wb.add_format({"border": 1, "border_color": "#E6E8EF", "valign": "top", "text_wrap": True})
        for j, (h_, w) in enumerate(cols):
            wp.write(3, j, h_, head)
            wp.set_column(j, j, w)
        for i, x in enumerate(v["proof"], start=4):
            wp.set_row(i, 132)
            wp.write(i, 0, x["risk"], top_)
            wp.write(i, 1, f"{x['name']}\n{x['code']}\n{x['manager']}", top_)
            wp.write(i, 2, "\n".join(f"{s['kind']}: {s['label']}" for s in x["signs"]) + ("\n\n" + x["why"] if x["why"] else ""), top_)
            for j, (jpg, url, cap) in enumerate([(x["selfie_jpg"], x["selfie_url"], f"{v['date_long']}")] +
                                                [(m["jpg"], m["url"], f"{m['name']} {m['date']}") for m in x["matches"][:1]], start=3):
                if jpg:
                    wp.insert_image(i, j, f"{cap}.jpg", {"image_data": io.BytesIO(jpg), "x_scale": 0.52, "y_scale": 0.52,
                                                         "x_offset": 4, "y_offset": 4, "url": url, "object_position": 1})
                elif url:
                    wp.write_url(i, j, url, link, "Open selfie")
                else:
                    wp.write(i, j, "no selfie", top_)
            r_lines = [x["from_usual"]] if x["from_usual"] else []
            wp.write(i, 5, "\n".join(r_lines) or "", top_)
            if x["att_map"]:
                wp.write_url(i, 5, x["att_map"], link, ("\n".join(r_lines) + "\n" if r_lines else "") + "Attendance place on the map")
        wp.autofilter(3, 0, 3 + len(v["proof"]), len(cols) - 1)
        wp.freeze_panes(4, 2)

    ai = v["ctx"].get("absent_info") or {}
    table("Absent", f"Absent – {v['date_long']}", "Did not mark attendance in Bizom (no leave recorded); longest absence first",
          [("Code", 10), ("Name", 28), ("Designation", 12), ("Zone", 10), ("Manager", 24), ("Last marked in Bizom", 14),
           ("Absent working days in a row", 13), ("Reason", 30)],
          sorted([[p["code"], p["name"], p["designation"], p["zone"], p["manager"], (ai.get(p["code"]) or {}).get("last_marked") or "not in the uploaded days",
                   (ai.get(p["code"]) or {}).get("streak"),
                   "Did not mark attendance in Bizom" if p["not_marked"] else "Marked absent in Bizom"] for p in v["not_marked"]],
                 key=lambda r_: (-(r_[6] or 0), r_[1])),
          "Nobody absent on this day.", fmt=lambda i, j, x: lvl["high"] if j == 6 and isinstance(x, int) and x >= 3 else None)

    has_calls = any(p.get("calls") for p in v["people"])
    cols = [("Code", "code", 10), ("Name", "name", 26), ("Designation", "designation", 11), ("Zone", "zone", 10), ("Manager", "manager", 22),
            ("Status", "status_label", 10), ("Leave / holiday", "leave", 16), ("Attendance time", "att", 11), ("First activity", "first", 11),
            ("Last activity", "last", 11), ("Time in market (h:mm)", "market", 11), ("KM", "km", 8), ("Day end", "eod", 10)]
    if has_calls:
        cols += [("Calls", "calls", 7), ("Productive", "productive", 9), ("Order value", "order_value", 11)]
    cols += [("Warning signs", "warn", 34), ("Location & selfie checks", "chk", 30), ("Patterns", "pat", 30)]
    if v["view"] != "team":
        cols.insert(5, ("HOD", "hod", 18))
    people = v["people"]

    def val(p, k):
        if k == "warn":
            return "; ".join(f["label"] for f in p["flags"])
        if k == "chk":
            return "; ".join(f"{s['kind']}: {s['label']}" for s in p.get("checks") or [])
        if k == "pat":
            return "; ".join(x["label"] for x in p.get("patterns") or [])
        return p.get(k)
    si = [k for _, k, _ in cols].index("status_label")
    table("Team list", f"Everyone – {v['date_long']}", f"{v['n']} people; filter any column with the buttons in the header",
          [(h_, w) for h_, _, w in cols], [[val(p, k) for _, k, _ in cols] for p in people], "No people.",
          fmt=lambda i, j, x: st.get(people[i]["status"]) if j == si else None)

    sit = v["ctx"].get("staff_issues") or {}
    if v["view"] == "hr" and (sit.get("possibly_left") or sit.get("never_in_bizom") or sit.get("doj_wrong")):
        rows = []
        for key, label, action in (("possibly_left", "Possibly left", "Confirm with the team head; mark Left on the staff list if gone."),
                                   ("never_in_bizom", "Never marks attendance in Bizom", "Remove from the Field Sales list, or ask them to mark in Bizom."),
                                   ("doj_wrong", "Joining date looks wrong", "Correct the date of joining on the staff list.")):
            rows += [[label, x["code"], x["name"], x["manager"], x["hod"], x["proof"], action] for x in sit.get(key, [])]
        table("Staff list to fix", "Staff list to fix", "People who never mark attendance in Bizom are not counted absent; the others are, until the list is fixed",
              [("Problem", 26), ("Code", 10), ("Name", 26), ("Team head", 22), ("HOD", 20), ("Proof", 80), ("Action", 44)], rows, "", freeze=3)

    if v["view"] == "hr" and v["data"]:
        wd = wb.add_worksheet("Data issues")
        excel_banner(wb, wd, [70], "Data issues", v["date_long"])
        wd.set_column(0, 0, 70)
        r = 3
        for title, items in (("In Bizom but not on the field sales staff list", v["data"].get("not_in_staff_list", [])),
                             ("Marked attendance in Bizom but Left on the staff list", v["data"].get("left_but_marked", []))):
            wd.write(r, 0, f"{title} ({len(items)})", head)
            for i, x in enumerate(items, start=r + 1):
                wd.write(i, 0, x)
            r += 2 + len(items)
        wd.write(r, 0, f"'Not Marked' in the EOD report: {v['data'].get('eod_not_marked', 0)} users", note)
        wd.write(r + 1, 0, f"Left out: {', '.join(f'{k} {n}' for k, n in v['data'].get('excluded', {}).items()) or 'none'}", note)
    wb.close()
    return buf.getvalue()


# ---------------------------------------------------------------- dashboard
def dashboard(v: dict) -> bytes:
    data = {"people": v["people"], "warnings": v["warnings"], "teams": v["teams"], "colors": COLORS, "labels": v["status_label"],
            "checks": v["checks"], "patterns": v.get("patterns") or [],
            "proof": [{k: x[k] for k in ("code", "name", "manager", "risk", "signs", "why", "selfie_url", "selfie_uri", "att_map", "eod_map",
                                          "att_time", "from_usual")} | {"matches": [{k: m[k] for k in ("name", "date", "url", "uri")} for m in x["matches"]]}
                      for x in v["proof"]]}
    js = json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
    return _env.get_template("sales_dashboard.html").render(v=v, logo=logo_data_uri(), data_json=js).encode("utf-8")
