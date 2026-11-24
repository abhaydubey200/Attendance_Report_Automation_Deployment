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


def pct_of_people(ps: list[dict]) -> float | None:
    """Attendance % of view rows (same rule as pct_of): (present + late + half of half days) / everyone not on a week off."""
    due = sum(1 for p in ps if p["status"] != "WEEK_OFF")
    eq = sum(1 for p in ps if p["status"] in ("PRESENT", "LATE")) + 0.5 * sum(1 for p in ps if p["status"] == "HALF_DAY")
    return round(100 * eq / due, 1) if due else None


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
    pk = (ctx or {}).get("pack")
    if pk:
        from sales import insights
        for p in people:
            p["hist"] = pk["people"].get(p["code"]) or {}
        out["pack"] = {k: pk[k] for k in ("days", "labels", "weekday_of", "trend", "heat_all", "weekdays")}
        out["scorecards"] = insights.scorecards(people, pk, (ctx or {}).get("team_trend") or [])
    else:
        out["pack"], out["scorecards"] = None, []
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
        h.append({"level": "medium", "text": f"Staff list to fix: {len(si.get('possibly_left', []))} possibly left (no attendance for "
                                              f"{si.get('working_days_checked')} working days), {len(si.get('never_in_bizom', []))} never mark "
                                              f"attendance, {len(si.get('doj_wrong', []))} joining date looks wrong. Proof in the Excel."})
    if v["view"] == "hr" and v["data"] and (v["data"].get("not_in_staff_list") or v["data"].get("left_but_marked")):
        h.append({"level": "low", "text": f"Data to fix: {len(v['data'].get('not_in_staff_list', []))} not on the staff list, "
                                           f"{len(v['data'].get('left_but_marked', []))} marked attendance though Left."})
    return h[:6]


def _checks_summary(checks: list[dict]) -> list[dict]:
    from sales.checks import summary
    return summary(checks)


# ---------------------------------------------------------------- email
ATTENTION_STATUS = ("ABSENT", "LATE", "HALF_DAY")
ATTENTION_SIGNS = {"NO_ACTIVITY", "VERY_SHORT_MARKET"}     # signs that question the attendance itself; visit signs are counted only


def _reason(p: dict) -> str:
    bits = []
    if p["status"] == "ABSENT":
        bits.append("did not mark attendance" + (f" ({p['absent_streak']} days in a row)" if (p.get("absent_streak") or 0) > 1 else ""))
    elif p["status"] == "LATE":
        bits.append(f"marked late at {p['att']}")
    elif p["status"] == "HALF_DAY":
        bits.append("half day")
    bits += [f["label"] for f in p["flags"] if f["code"] in ATTENTION_SIGNS] + [f"{c['kind']}: {c['label']}" for c in p.get("checks") or []]
    return "; ".join(bits)


def _tally(ps: list[dict]) -> dict:
    c = Counter(p["status"] for p in ps)
    due = len(ps) - c["WEEK_OFF"]
    pct = round(100 * (c["PRESENT"] + c["LATE"] + 0.5 * c["HALF_DAY"]) / due, 1) if due else None
    return {"people": len(ps), "present": c["PRESENT"], "late": c["LATE"], "half": c["HALF_DAY"], "absent": c["ABSENT"],
            "leave": c["LEAVE"], "week_off": c["WEEK_OFF"], "pct": pct, "attention": sum(1 for p in ps if p["attention"])}


def routing_sections(v: dict, detail: set[str] | None, exceptions: list[dict] | None = None) -> dict:
    """Adds to the view: tally, the people needing attention (only the recipient's own reports) grouped by territory,
    and the summary tables - HOD: by manager and territory; Director / HR: by HOD and manager."""
    from sales.routing import title
    for p in v["people"]:
        # attention = absent / late / half day, or a SERIOUS warning sign or check; minor signs stay in the attachments
        # location / selfie checks only reach an email after the trust gate (proven by HR reviews), so each one is listed
        p["attention"] = p["status"] in ATTENTION_STATUS or any(f["code"] in ATTENTION_SIGNS for f in p["flags"]) or bool(p.get("checks"))
        p["reason"] = _reason(p) if p["attention"] else ""
        p["display_name"] = title(p["name"])
    own = [p for p in v["people"] if detail is None or p["code"] in detail]
    v["visit_signs"] = sum(1 for p in own if any(f["code"] not in ATTENTION_SIGNS for f in p["flags"]))
    v["tally"] = _tally(v["people"])
    v["own_tally"] = _tally(own)
    groups: dict[str, list[dict]] = defaultdict(list)
    if v["view"] == "team":
        for p in own:
            if p["attention"]:
                groups[p["zone"] or "No territory"].append(p)
    v["attention_groups"] = [{"territory": z, "people": sorted(ps, key=lambda p: (ATTENTION_STATUS.index(p["status"]) if p["status"] in ATTENTION_STATUS else 9, p["name"]))}
                             for z, ps in sorted(groups.items())]
    v["is_hod_view"] = v["view"] == "team" and detail is not None and len(detail) < len(v["people"])
    rows: dict[tuple, list[dict]] = defaultdict(list)
    if v["is_hod_view"]:                     # one row per reporting manager; their territories in the second column
        for p in v["people"]:
            rows[(title(p["manager"]) or "No reporting manager", "")].append(p)
        rows = {(a, ", ".join(sorted({p["zone"] or "-" for p in ps}))): ps for (a, _), ps in rows.items()}
    elif v["view"] != "team":
        for p in v["people"]:
            rows[(title(p["hod"]) or "No HOD", title(p["manager"]) or "No reporting manager")].append(p)
    summ = [{"a": a, "b": b, **_tally(ps)} for (a, b), ps in rows.items()]
    v["summary_rows"] = sorted(summ, key=lambda r: ((r["a"], r["pct"] if r["pct"] is not None else 999) if v["view"] != "team"
                                                    else (r["pct"] if r["pct"] is not None else 999, r["a"])))
    v["summary_cols"] = ("Reporting manager", "Territories") if v["is_hod_view"] else ("HOD", "Reporting manager")
    v["summary_title"] = "reporting manager and territory" if v["is_hod_view"] else "HOD and reporting manager"
    v["routing_exceptions"] = exceptions or []
    tr = ((v.get("pack") or {}).get("trend") or [])[-7:]
    week = [{"label": t["weekday"], "day": t["label"], "pct": None if t.get("off_day") else t["pct"]} for t in tr]
    past = [t["pct"] for t in week[:-1] if t["pct"] is not None]
    v["week"] = week if sum(1 for t in week if t["pct"] is not None) >= 2 else []
    v["week_avg"] = round(sum(past) / len(past), 1) if past else None
    v["recipient"] = title(v["recipient"]) if v["recipient"].isupper() else v["recipient"]
    return v


def email_html(v: dict) -> str:
    return _env.get_template("sales_mail.html").render(v=v)


def email_text(v: dict) -> str:
    t = v.get("tally") or _tally(v["people"])
    lines = [f"Dear {v['recipient']},", "",
             f"Field sales attendance for {v['weekday']}, {v['date_long']}.",
             f"Total {t['people']} | Present {t['present']} | Late {t['late']} | Half day {t['half']} | Absent {t['absent']} | "
             f"Leave {t['leave']} | Week off {t['week_off']} | Attendance {t['pct'] if t['pct'] is not None else '-'}%", ""]
    if v.get("week"):
        lines += ["Last 7 report days: " + " | ".join(f"{t['label']} {t['day']} {'off' if t['pct'] is None else '%g%%' % t['pct']}" for t in v["week"]), ""]
    for g in v.get("attention_groups") or []:
        lines += [f"Needs attention - {g['territory']}:"] + [f"- {p['display_name']} ({p['code']}): {p['reason']}" for p in g["people"]] + [""]
    if v.get("visit_signs"):
        lines += [f"Visit checks: {v['visit_signs']} people have warning signs about their outlet visits - see the attachments.", ""]
    if v.get("summary_rows"):
        lines += [f"Summary by {v['summary_title']}:"] + [
            f"- {r['a']} / {r['b']}: {r['people']} people, {r['absent']} absent, {r['late']} late, attendance {r['pct'] if r['pct'] is not None else '-'}%"
            for r in v["summary_rows"]] + [""]
    if v.get("routing_exceptions"):
        lines += ["Records that could not be routed (please fix on the staff list):"] + [
            f"- {x['code']} {x['name']}: {x['issue']} - {x['detail']}" for x in v["routing_exceptions"]] + [""]
    if v.get("feedback"):
        lines += ["Was this right? Your answer makes the checks more accurate:"] + [
            f"- {f['name']} ({f['sign'].lower()}): right {f['right']} | not right {f['wrong']}" for f in v["feedback"]] + [""]
    lines += ["Automated email from the APIS HR Portal."]
    return "\n".join(lines)


# ---------------------------------------------------------------- Excel
def excel(v: dict) -> bytes:
    """One workbook per email: a Summary, then one styled table per list (filter buttons, banded rows, frozen header).
    Columns nobody has data for are left out; every sheet says what it is in its title line."""
    buf = io.BytesIO()
    wb = xlsxwriter.Workbook(buf, {"in_memory": True, "strings_to_formulas": False, "strings_to_urls": False})
    head = wb.add_format({"bold": True, "font_color": "#FFFFFF", "bg_color": "#3D2A10", "text_wrap": True, "valign": "vcenter", "border": 1})
    cell = wb.add_format({"valign": "top"})
    wrap = wb.add_format({"valign": "top", "text_wrap": True})
    big = wb.add_format({"border": 1, "border_color": "#E6E8EF", "bold": True, "font_size": 13, "font_color": "#3D2A10", "align": "center"})
    bold = wb.add_format({"border": 1, "border_color": "#E6E8EF", "bold": True, "font_color": "#3D2A10"})
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
              fmt=None, freeze: int = 2, height: int | None = None, footnote: str | None = None, tname: str | None = None):
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
            "columns": [{"header": h, "header_format": head} for h, _ in cols], **({"name": tname} if tname else {})})
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

    # ---- Dashboard: KPI cards, charts (status, marking times, 30-day trend, team heads) and a clickable contents list
    ws = wb.add_worksheet("Dashboard")
    dash = ws
    ws.hide_gridlines(2)
    widths = [24, 9, 3] + [11.5] * 10
    for j, w in enumerate(widths):
        ws.set_column(j, j, w)
    excel_banner(wb, ws, widths, f"Field sales attendance – {v['date_long']} ({v['weekday']})", v["recipient"])
    n_ = v["counts"]
    cards = [("ATTENDANCE", f"{v['pct']}%" if v["pct"] is not None else "–", "#15803D" if (v["pct"] or 0) >= 90 else "#B45309" if (v["pct"] or 0) >= 75 else "#B91C1C",
              f"{n_.get('PRESENT', 0) + n_.get('LATE', 0)} worked · {n_.get('HALF_DAY', 0)} half day"),
             ("ABSENT", n_.get("ABSENT", 0), "#DC2626", f"{sum(1 for p in v['not_marked'] if p['not_marked'])} did not mark"),
             ("LATE", n_.get("LATE", 0), "#D97706", "after 10:30 AM"),
             ("LEAVE", n_.get("LEAVE", 0), "#64748B", f"{n_.get('WEEK_OFF', 0)} week off"),
             ("NEEDS CHECKING", len(v["flagged"]), "#7C3AED", f"{v['flagged_high']} serious"),
             ("PATTERNS", len(v.get("patterns") or []), "#0D9488", "people with repeat patterns")]

    for k, (lab, val_, colr, subt) in enumerate(cards):
        cs = [(0, 1), (3, 4), (5, 6), (7, 8), (9, 10), (11, 12)][k]
        fl = wb.add_format({"bold": True, "font_size": 9, "font_color": "#5D6577", "bg_color": "#F8FAFC", "top": 5, "top_color": colr, "left": 1, "right": 1,
                            "left_color": "#E6E8EF", "right_color": "#E6E8EF", "align": "left", "indent": 1})
        fv = wb.add_format({"bold": True, "font_size": 22, "font_color": colr, "bg_color": "#F8FAFC", "left": 1, "right": 1, "left_color": "#E6E8EF",
                            "right_color": "#E6E8EF", "align": "left", "indent": 1, "valign": "vcenter"})
        fs = wb.add_format({"font_size": 9, "font_color": "#5D6577", "bg_color": "#F8FAFC", "bottom": 1, "left": 1, "right": 1, "border_color": "#E6E8EF",
                            "align": "left", "indent": 1})
        ws.merge_range(4, cs[0], 4, cs[1], lab, fl)
        ws.merge_range(5, cs[0], 5, cs[1], val_, fv)
        ws.merge_range(6, cs[0], 6, cs[1], subt, fs)
    ws.set_row(5, 34)
    sec = wb.add_format({"bold": True, "font_size": 12, "font_color": "#3D2A10", "bottom": 2, "bottom_color": "#F5B800"})
    # status table + doughnut
    ws.write(8, 0, "Status on this day", sec)
    ws.write(9, 0, "Status", head)
    ws.write(9, 1, "People", head)
    sts = [k for k in v["status_label"] if v["counts"].get(k)]
    for i, k in enumerate(sts, start=10):
        ws.write(i, 0, v["status_label"][k], st.get(k, bold))
        ws.write_number(i, 1, v["counts"][k], cell)
    if sts:
        dn = wb.add_chart({"type": "doughnut"})
        dn.add_series({"name": "Status", "categories": ["Dashboard", 10, 0, 9 + len(sts), 0], "values": ["Dashboard", 10, 1, 9 + len(sts), 1],
                       "points": [{"fill": {"color": COLORS[k]}} for k in sts], "data_labels": {"value": True, "leader_lines": True}})
        dn.set_hole_size(55)
        dn.set_title({"name": "People by status", "name_font": {"size": 11}})
        dn.set_legend({"position": "right"})
        dn.set_size({"width": 390, "height": 280})
        dn.set_chartarea({"border": {"none": True}})
        ws.insert_chart(8, 3, dn, {"x_offset": 4, "y_offset": 4})
    # marking times table + column chart
    bins = [(0, 540, "Before 9:00"), (540, 570, "9:00–9:30"), (570, 600, "9:30–10:00"), (600, 630, "10:00–10:30"), (630, 660, "10:30–11:00"),
            (660, 720, "11:00–12:00"), (720, 1440, "After 12:00")]
    mrow = 11 + len(sts) + 1
    ws.write(mrow - 1, 0, "Marking times", sec)
    ws.write(mrow, 0, "Marked", head)
    ws.write(mrow, 1, "People", head)
    for i, (a_, b_, lab) in enumerate(bins, start=mrow + 1):
        ws.write(i, 0, lab, bold)
        ws.write_number(i, 1, sum(1 for p in v["people"] if p.get("att_min") is not None and a_ <= p["att_min"] < b_), cell)
    hc = wb.add_chart({"type": "column"})
    hc.add_series({"name": "People", "categories": ["Dashboard", mrow + 1, 0, mrow + len(bins), 0], "values": ["Dashboard", mrow + 1, 1, mrow + len(bins), 1],
                   "points": [{"fill": {"color": "#F59E0B" if a_ >= 630 else "#0D9488"}} for a_, _, _ in bins], "gap": 40, "data_labels": {"value": True}})
    hc.set_title({"name": "Attendance marking time (amber = late)", "name_font": {"size": 11}})
    hc.set_legend({"none": True})
    hc.set_size({"width": 390, "height": 280})
    hc.set_chartarea({"border": {"none": True}})
    ws.insert_chart(8 + 15, 3, hc, {"x_offset": 4, "y_offset": 4})
    dash_charts_at = (8, 8)          # trend + team-head charts go here once those sheets exist (below)
    # warning signs + highlights
    wrow = max(mrow + len(bins) + 2, 8 + 31)
    ws.write(wrow, 0, "Warning signs on this day – for checking, not proof", sec)
    if v["warnings"]:
        for j, h_ in enumerate(("Warning sign", "People")):
            ws.write(wrow + 1, j, h_, head)
        for i, w in enumerate(v["warnings"], start=wrow + 2):
            ws.write(i, 0, w["label"], lvl[w["level"]])
            ws.write_number(i, 1, w["n"], cell)
    else:
        ws.write(wrow + 1, 0, "Nothing to check on this day.", note)
    ws.write(wrow, 3, "Highlights (as in the email)", sec)
    for i, x in enumerate(v["highlights"], start=wrow + 1):
        ws.merge_range(i, 3, i, 12, x["text"], lvl[x["level"]])
        ws.set_row(i, 30)
    contents_row = max(wrow + 3 + len(v["warnings"]), wrow + 2 + len(v["highlights"])) + 1
    if v.get("trend"):
        ws.write(contents_row - 1, 0, f"Trend: {v['trend']}", note)
        contents_row += 1

    # ---- pivot-style sheets: trend (with a chart), team scorecard (with a chart), 30-day grid
    pk = v.get("pack")
    if pk and pk["trend"]:
        wt = wb.add_worksheet("Trend")
        excel_banner(wb, wt, [12, 8, 14, 9, 9, 12], f"Last {len(pk['trend'])} uploaded days", "Attendance % on working days (Sundays / holidays left out)")
        heads = [("Date", 12), ("Day", 8), ("Attendance %", 14), ("Absent", 9), ("Late", 9), ("Off (holiday)", 12)]
        for j, (h_, w) in enumerate(heads):
            wt.write(3, j, h_, head)
            wt.set_column(j, j, w)
        for i, t in enumerate(pk["trend"], start=4):
            wt.write(i, 0, t["label"], cell)
            wt.write(i, 1, t["weekday"], cell)
            if t["pct"] is None:
                wt.write(i, 2, "off day", note)
            else:
                wt.write_number(i, 2, t["pct"], pfmt(t["pct"]))
            wt.write(i, 3, t["absent"], cell)
            wt.write(i, 4, t["late"], cell)
            wt.write(i, 5, t["off"] if t.get("off_day") else "", cell)
        last = 3 + len(pk["trend"])
        ch = wb.add_chart({"type": "line"})
        ch.add_series({"name": "Attendance %", "categories": ["Trend", 4, 0, last, 0], "values": ["Trend", 4, 2, last, 2],
                       "line": {"color": "#3D2A10", "width": 2.25}, "marker": {"type": "circle", "size": 5, "fill": {"color": "#F5B800"}}})
        col = wb.add_chart({"type": "column"})
        col.add_series({"name": "Absent", "categories": ["Trend", 4, 0, last, 0], "values": ["Trend", 4, 3, last, 3],
                        "fill": {"color": "#FCA5A5"}, "y2_axis": True})
        ch.combine(col)
        ch.set_title({"name": "Attendance % and absent people", "name_font": {"size": 12}})
        ch.set_y_axis({"min": 40, "max": 100, "name": "%"})
        col.set_y2_axis({"name": "Absent"})
        ch.set_legend({"position": "bottom"})
        ch.set_size({"width": 760, "height": 340})
        wt.insert_chart(3, 7, ch)
        wt.freeze_panes(4, 1)
        tc = wb.add_chart({"type": "line"})
        tc.add_series({"name": "Attendance %", "categories": ["Trend", 4, 0, last, 0], "values": ["Trend", 4, 2, last, 2],
                       "line": {"color": "#3D2A10", "width": 2}, "marker": {"type": "circle", "size": 4, "fill": {"color": "#F5B800"}}})
        tc2 = wb.add_chart({"type": "column"})
        tc2.add_series({"name": "Absent", "categories": ["Trend", 4, 0, last, 0], "values": ["Trend", 4, 3, last, 3], "fill": {"color": "#FCA5A5"}, "y2_axis": True})
        tc.combine(tc2)
        tc.set_title({"name": f"Last {len(pk['trend'])} report days – attendance % (off days left out)", "name_font": {"size": 11}})
        tc.set_y_axis({"min": 40, "max": 100})
        tc.set_legend({"position": "bottom"})
        tc.set_size({"width": 580, "height": 280})
        tc.set_chartarea({"border": {"none": True}})
        dash.insert_chart(dash_charts_at[0], dash_charts_at[1], tc, {"x_offset": 10, "y_offset": 4})

    sc = v.get("scorecards") or []
    if len(sc) > 1:
        cols_sc = [("Team head", 26), ("People", 8), (v["date_long"], 12), ("Last 30 days %", 13), ("4-week change", 12), ("Late % (30 days)", 13),
                   ("Absent (this day)", 11), ("Signs (this day)", 10), ("Patterns", 9)] + [(w, 7) for w in (pk["weekdays"] if pk else [])] + [("Lowest 30-day attendance", 40)]
        rows_sc = [[r["team_head"], r["people"], r["pct"], r["pct30"], r["change4"], r["late30_pct"], r["absent"], r["signs"], r["patterns"],
                    *(r["heat"] if pk else []), "; ".join(r["lowest"])] for r in sc]
        nh = len(pk["weekdays"]) if pk else 0
        ws_sc = table("Team scorecard", f"Team heads – {v['date_long']}",
                      "Lowest 30-day attendance first · weekday columns = attendance % on that weekday over the last 12 weeks (working days)",
                      cols_sc, rows_sc, "", freeze=1,
                      fmt=lambda i, j, x: (pfmt(x) if j in (2, 3) and isinstance(x, (int, float)) else
                                           (neg if isinstance(x, (int, float)) and x <= -10 else pos if isinstance(x, (int, float)) and x > 0 else None) if j == 4 else None))
        if nh:
            ws_sc.conditional_format(4, 9, 3 + len(rows_sc), 8 + nh, {"type": "3_color_scale", "min_color": "#F8696B", "mid_color": "#FFEB84",
                                                                      "max_color": "#63BE7B", "min_type": "num", "min_value": 60,
                                                                      "mid_type": "num", "mid_value": 85, "max_type": "num", "max_value": 100})
        bar = wb.add_chart({"type": "bar"})
        bar.add_series({"name": "Last 30 days %", "categories": ["Team scorecard", 4, 0, 3 + len(rows_sc), 0],
                        "values": ["Team scorecard", 4, 3, 3 + len(rows_sc), 3], "fill": {"color": "#3D2A10"},
                        "data_labels": {"value": True, "num_format": "0.0"}})
        bar.set_title({"name": "Attendance by team head – last 30 days", "name_font": {"size": 12}})
        bar.set_x_axis({"min": 50, "max": 100})
        bar.set_legend({"none": True})
        bar.set_size({"width": 620, "height": max(260, 26 * len(rows_sc) + 80)})
        ws_sc.insert_chart(6 + len(rows_sc), 0, bar)
        top_n = min(10, len(rows_sc))
        db = wb.add_chart({"type": "bar"})
        db.add_series({"name": "Last 30 days %", "categories": ["Team scorecard", 4, 0, 3 + top_n, 0], "values": ["Team scorecard", 4, 3, 3 + top_n, 3],
                       "fill": {"color": "#3D2A10"}, "data_labels": {"value": True, "num_format": "0.0"}, "gap": 40})
        db.set_title({"name": f"Lowest {top_n} team heads – last 30 days %", "name_font": {"size": 11}})
        db.set_x_axis({"min": 50, "max": 100})
        db.set_y_axis({"reverse": True})
        db.set_legend({"none": True})
        db.set_size({"width": 580, "height": 280})
        db.set_chartarea({"border": {"none": True}})
        dash.insert_chart(dash_charts_at[0] + 15, dash_charts_at[1], db, {"x_offset": 10, "y_offset": 4})

    if pk and v["people"]:
        days = pk["labels"]
        wg = wb.add_worksheet("Last 30 days")
        fixed = [("Code", 10), ("Name", 24), ("Team head", 18), ("30-day %", 9), ("Late", 6), ("Absent", 7), ("Leave", 6), ("Usual start", 10)]
        excel_banner(wb, wg, [w for _, w in fixed] + [4] * len(days), f"Day by day – last {len(days)} uploaded days to {v['date_long']}",
                     "P present · L late · H half day · A absent · V leave · O week off / holiday · - not in that day's data")
        dh = wb.add_format({"bold": True, "font_color": "#FFFFFF", "bg_color": "#3D2A10", "align": "center", "rotation": 90, "border": 1, "font_size": 9})
        for j, (h_, w) in enumerate(fixed):
            wg.write(3, j, h_, head)
            wg.set_column(j, j, w)
        for k, (lab, wd) in enumerate(zip(days, pk["weekday_of"])):
            wg.write(3, len(fixed) + k, f"{lab} {wd}", dh)
        wg.set_column(len(fixed), len(fixed) + len(days) - 1, 3.6)
        wg.set_row(3, 64)
        center = wb.add_format({"align": "center", "font_size": 9, "border": 1, "border_color": "#FFFFFF"})
        ppl = sorted(v["people"], key=lambda p: ((p.get("hist") or {}).get("pct30") if (p.get("hist") or {}).get("pct30") is not None else 999, p["name"]))
        for i, p in enumerate(ppl, start=4):
            h = p.get("hist") or {}
            for j, val in enumerate([p["code"], p["name"], p["manager"], h.get("pct30"), h.get("late30"), h.get("absent30"), h.get("leave30"), h.get("usual_start")]):
                wg.write(i, j, "" if val is None else val, pfmt(val) if j == 3 and isinstance(val, (int, float)) else cell)
            for k, ch_ in enumerate((h.get("strip") or "-" * len(days)).ljust(len(days), "-")[:len(days)]):
                wg.write(i, len(fixed) + k, ch_, center)
        first, lastc = len(fixed), len(fixed) + len(days) - 1
        for code, bg, fg in (("P", "#C6EFCE", "#006100"), ("L", "#FFEB9C", "#9C5700"), ("H", "#FCE4D6", "#9C5700"), ("A", "#FFC7CE", "#9C0006"),
                             ("V", "#D9E1F2", "#1F3864"), ("O", "#EDEDED", "#7F7F7F")):
            wg.conditional_format(4, first, 3 + len(ppl), lastc, {"type": "cell", "criteria": "==", "value": f'"{code}"',
                                                                  "format": wb.add_format({"bg_color": bg, "font_color": fg, "bold": True})})
        wg.autofilter(3, 0, 3 + len(ppl), lastc)
        wg.freeze_panes(4, 2)

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
              [("Code", 10), ("Name", 26), ("Designation", 11), ("Manager", 22), ("On the day", 12), ("Pattern", 30), ("Proof (dates)", 80)],
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
        excel_banner(wb, wp, [w for _, w in cols], f"Proof – {v['date_long']}", "Selfies are small copies made for this workbook; click one to open the original")
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
    table("Absent", f"Absent – {v['date_long']}", "Did not mark attendance (no leave recorded); longest absence first",
          [("Code", 10), ("Name", 28), ("Designation", 12), ("Zone", 10), ("Manager", 24), ("Last marked", 14),
           ("Absent working days in a row", 13), ("Reason", 30)],
          sorted([[p["code"], p["name"], p["designation"], p["zone"], p["manager"], (ai.get(p["code"]) or {}).get("last_marked") or "not in the uploaded days",
                   (ai.get(p["code"]) or {}).get("streak"),
                   "Did not mark attendance" if p["not_marked"] else "Marked absent"] for p in v["not_marked"]],
                 key=lambda r_: (-(r_[6] or 0), r_[1])),
          "Nobody absent on this day.", fmt=lambda i, j, x: lvl["high"] if j == 6 and isinstance(x, int) and x >= 3 else None)

    has_calls = any(p.get("calls") for p in v["people"])
    cols = [("Code", "code", 10), ("Name", "name", 26), ("Designation", "designation", 11), ("Zone", "zone", 10), ("Team head", "manager", 22),
            ("Status", "status_label", 10), ("Leave / holiday", "leave", 16), ("Attendance time", "att", 11), ("First activity", "first", 11),
            ("Last activity", "last", 11), ("Time in market (h:mm)", "market", 11), ("KM", "km", 8), ("Day end", "eod", 10)]
    if has_calls:
        cols += [("Calls", "calls", 7), ("Productive", "productive", 9), ("Order value", "order_value", 11)]
    if pk:
        cols += [("30-day %", "h_pct30", 9), ("Absent (30 days)", "h_absent30", 9), ("Late (30 days)", "h_late30", 9), ("Usual start", "h_usual_start", 10)]
    cols += [("Risk", "risk", 6), ("Warning signs", "warn", 34), ("Location & selfie checks", "chk", 30), ("Patterns", "pat", 30)]
    if v["view"] != "team":
        cols.insert(5, ("HOD", "hod", 18))
    people = sorted(v["people"], key=lambda p: (not p.get("attention"), p["name"]))      # roster: people needing attention first

    def val(p, k):
        if k == "warn":
            return "; ".join(f["label"] for f in p["flags"])
        if k == "chk":
            return "; ".join(f"{s['kind']}: {s['label']}" for s in p.get("checks") or [])
        if k == "pat":
            return "; ".join(x["label"] for x in p.get("patterns") or [])
        if k.startswith("h_"):
            return (p.get("hist") or {}).get(k[2:])
        return p.get(k)
    si = [k for _, k, _ in cols].index("status_label")
    pj = [k for _, k, _ in cols].index("h_pct30") if pk else -1
    wl_ = table("Team list", f"Everyone – {v['date_long']}", f"{v['n']} people; filter any column with the buttons in the header · the Pivot sheets count from this table",
                [(h_, w) for h_, _, w in cols], [[val(p, k) for _, k, _ in cols] for p in people], "No people.",
                fmt=lambda i, j, x: st.get(people[i]["status"]) if j == si else pfmt(x) if j == pj and isinstance(x, (int, float)) else None, tname="TeamList")
    if people and pk:
        wl_.conditional_format(4, pj, 3 + len(people), pj, {"type": "data_bar", "bar_color": "#93C5FD", "bar_solid": True, "min_type": "num", "min_value": 0,
                                                             "max_type": "num", "max_value": 100})

    # ---- live pivots: COUNTIFS over the TeamList table (cached values filled in, so phones / previews show them too)
    pv_st = [k for k in ("PRESENT", "LATE", "HALF_DAY", "ABSENT", "LEAVE", "WEEK_OFF")]
    pvh = wb.add_format({"bold": True, "font_color": "#FFFFFF", "bg_color": "#3D2A10", "text_wrap": True, "valign": "vcenter", "align": "center", "border": 1})
    pvn = wb.add_format({"border": 1, "border_color": "#E6E8EF", "align": "center"})
    pvt = wb.add_format({"border": 1, "border_color": "#E6E8EF", "bold": True, "bg_color": "#F1F5F9", "align": "center"})
    pvp = wb.add_format({"border": 1, "border_color": "#E6E8EF", "bold": True, "num_format": "0.0", "align": "center"})
    pvpt = wb.add_format({"border": 1, "border_color": "#E6E8EF", "bold": True, "num_format": "0.0", "align": "center", "bg_color": "#F1F5F9"})

    def pivot_sheet(sname: str, title: str, key_head: str, key_of):
        if not people:
            return
        keys = sorted({key_of(p) or "—" for p in people}, key=lambda k_: (-sum(1 for p in people if (key_of(p) or "—") == k_), k_))
        if len(keys) < 2:
            return
        wsx = wb.add_worksheet(sname)
        heads = [key_head, "People"] + [v["status_label"][k] for k in pv_st] + ["Attendance %", "Needs checking"]
        wds = [28, 8] + [9] * len(pv_st) + [12, 10]
        excel_banner(wb, wsx, wds, title, "Live: counted with formulas from the Team list sheet – edit or fix a row there and these numbers follow")
        for j, (h_, w) in enumerate(zip(heads, wds)):
            wsx.write(3, j, h_, pvh)
            wsx.set_column(j, j, w)
        wsx.set_row(3, 32)
        kcol = {"Team head": "Team head", "Zone": "Zone", "Designation": "Designation"}[key_head]
        for i, k_ in enumerate(keys, start=4):
            ps = [p for p in people if (key_of(p) or "—") == k_]
            crit = f'TeamList[{kcol}],$A{i + 1}' if k_ != "—" else f'TeamList[{kcol}],""'
            wsx.write(i, 0, k_, bold)
            wsx.write_formula(i, 1, f"=COUNTIFS({crit})", pvn, len(ps))
            for j, s_ in enumerate(pv_st, start=2):
                c_ = sum(1 for p in ps if p["status"] == s_)
                wsx.write_formula(i, j, f'=COUNTIFS({crit},TeamList[Status],"{v["status_label"][s_]}")', pvn, c_)
            due = len(ps) - sum(1 for p in ps if p["status"] == "WEEK_OFF")
            pc_ = pct_of_people(ps)
            cl = lambda j_: chr(65 + j_)  # noqa: E731
            wsx.write_formula(i, 2 + len(pv_st), f"=IFERROR(ROUND(100*({cl(2)}{i + 1}+{cl(3)}{i + 1}+0.5*{cl(4)}{i + 1})/({cl(1)}{i + 1}-{cl(7)}{i + 1}),1),\"\")",
                              pvp, pc_ if due else "")
            wsx.write_formula(i, 3 + len(pv_st), f'=COUNTIFS({crit},TeamList[Warning signs],"<>")', pvn, sum(1 for p in ps if p["flags"]))
        tr = 4 + len(keys)
        wsx.write(tr, 0, "Total", pvt)
        for j in range(1, 2 + len(pv_st)):
            col_ = chr(65 + j)
            wsx.write_formula(tr, j, f"=SUM({col_}5:{col_}{tr})", pvt, sum(1 for p in people if j == 1 or p["status"] == pv_st[j - 2]))
        wsx.write_formula(tr, 2 + len(pv_st), f"=IFERROR(ROUND(100*(C{tr + 1}+D{tr + 1}+0.5*E{tr + 1})/(B{tr + 1}-H{tr + 1}),1),\"\")", pvpt, v["pct"] if v["pct"] is not None else "")
        wsx.write_formula(tr, 3 + len(pv_st), f"=SUM(J5:J{tr})", pvt, sum(1 for p in people if p["flags"]))
        wsx.conditional_format(4, 2 + len(pv_st), tr - 1, 2 + len(pv_st), {"type": "3_color_scale", "min_color": "#F8696B", "mid_color": "#FFEB84",
                               "max_color": "#63BE7B", "min_type": "num", "min_value": 60, "mid_type": "num", "mid_value": 85, "max_type": "num", "max_value": 100})
        wsx.conditional_format(4, 5, tr - 1, 5, {"type": "data_bar", "bar_color": "#FCA5A5", "bar_solid": True})
        wsx.autofilter(3, 0, tr - 1, len(heads) - 1)
        wsx.freeze_panes(4, 1)
        chx = wb.add_chart({"type": "bar", "subtype": "stacked"})
        for j, s_ in enumerate(pv_st, start=2):
            chx.add_series({"name": [sname, 3, j], "categories": [sname, 4, 0, tr - 1, 0], "values": [sname, 4, j, tr - 1, j],
                            "fill": {"color": COLORS[s_]}, "gap": 40})
        chx.set_title({"name": f"People by status – by {key_head.lower()}", "name_font": {"size": 11}})
        chx.set_y_axis({"reverse": True})
        chx.set_legend({"position": "bottom"})
        chx.set_size({"width": 720, "height": max(300, 24 * len(keys) + 110)})
        wsx.insert_chart(tr + 2, 0, chx)

    pivot_sheet("Pivot - team heads", f"Team heads × status – {v['date_long']}", "Team head", lambda p: p["manager"])
    pivot_sheet("Pivot - zones", f"Zones × status – {v['date_long']}", "Zone", lambda p: p["zone"])
    pivot_sheet("Pivot - designations", f"Designations × status – {v['date_long']}", "Designation", lambda p: p["designation"])

    sit = v["ctx"].get("staff_issues") or {}
    if v["view"] == "hr" and (sit.get("possibly_left") or sit.get("never_in_bizom") or sit.get("doj_wrong")):
        rows = []
        for key, label, action in (("possibly_left", "Possibly left", "Confirm with the team head; mark Left on the staff list if gone."),
                                   ("never_in_bizom", "Never marks attendance", "Remove from the Field Sales list, or ask them to mark attendance in the field app."),
                                   ("doj_wrong", "Joining date looks wrong", "Correct the date of joining on the staff list.")):
            rows += [[label, x["code"], x["name"], x["manager"], x["hod"], x["proof"], action] for x in sit.get(key, [])]
        table("Staff list to fix", "Staff list to fix", "People who never mark attendance are not counted absent; the others are, until the list is fixed",
              [("Problem", 26), ("Code", 10), ("Name", 26), ("Team head", 22), ("HOD", 20), ("Proof", 80), ("Action", 44)], rows, "", freeze=3)

    if v["view"] == "hr" and v["data"]:
        wd = wb.add_worksheet("Data issues")
        excel_banner(wb, wd, [70], "Data issues", v["date_long"])
        wd.set_column(0, 0, 70)
        r = 3
        for title, items in (("Marked attendance but not on the field sales staff list", v["data"].get("not_in_staff_list", [])),
                             ("Marked attendance but Left on the staff list", v["data"].get("left_but_marked", []))):
            wd.write(r, 0, f"{title} ({len(items)})", head)
            for i, x in enumerate(items, start=r + 1):
                wd.write(i, 0, x)
            r += 2 + len(items)
        wd.write(r, 0, f"'Not Marked' in the EOD report: {v['data'].get('eod_not_marked', 0)} users", note)
        wd.write(r + 1, 0, f"Left out: {', '.join(f'{k} {n}' for k, n in v['data'].get('excluded', {}).items()) or 'none'}", note)

    about = {"Trend": "Day-by-day attendance % and absences, last 30 report days, with chart", "Team scorecard": "Every team head: this day, 30 days, 4-week change, weekday heat",
             "Last 30 days": "Each person's last 30 days as a colour grid", "By team": "HOD × zonal head, this day", "Needs checking": "Warning signs, most serious first",
             "Patterns": "Repeat patterns with the dates", "Team heads - 4 weeks": "Team heads week by week", "Location & selfie checks": "Location and selfie checks, highest risk first",
             "Proof": "Selfies and map links behind the checks", "Absent": "Who did not mark, longest absence first", "Team list": "Everyone, every column – the master list",
             "Pivot - team heads": "Live counts by team head and status", "Pivot - zones": "Live counts by zone and status",
             "Pivot - designations": "Live counts by designation and status", "Staff list to fix": "Staff list problems for HR", "Data issues": "File problems for HR"}
    link = wb.add_format({"font_color": "#1D4ED8", "underline": 1, "bold": True})
    dash.write(contents_row, 0, "Contents – click a sheet to open it", sec)
    k_ = contents_row + 1
    for wsx in wb.worksheets():
        if wsx.name == "Dashboard":
            continue
        dash.write_url(k_, 0, f"internal:'{wsx.name}'!A1", link, wsx.name)
        dash.merge_range(k_, 1, k_, 8, about.get(wsx.name, ""), note)
        k_ += 1
    tab = {"Dashboard": "#F5B800", "Needs checking": "#DC2626", "Location & selfie checks": "#DC2626", "Proof": "#DC2626", "Absent": "#DC2626",
           "Patterns": "#D97706", "Staff list to fix": "#64748B", "Data issues": "#64748B"}
    back = wb.add_format({"font_color": "#1D4ED8", "underline": 1, "font_size": 9})
    for wsx in wb.worksheets():
        wsx.set_tab_color(tab.get(wsx.name, "#3D2A10"))
        wsx.set_landscape()
        wsx.set_paper(9)
        wsx.fit_to_pages(1, 0)
        wsx.set_margins(0.4, 0.4, 0.5, 0.5)
        wsx.set_footer(f"&L&8Field sales – {v['date_long']}&R&8Page &P of &N")
        if wsx.name != "Dashboard":
            wsx.hide_gridlines(2)
            wsx.repeat_rows(3)
            wsx.write_url(0, 0, "internal:'Dashboard'!A1", back, "◂ Dashboard")
    dash.activate()
    dash.set_first_sheet()
    wb.close()
    return buf.getvalue()


# ---------------------------------------------------------------- dashboard
def dashboard(v: dict) -> bytes:
    data = {"people": v["people"], "warnings": v["warnings"], "teams": v["teams"], "colors": COLORS, "labels": v["status_label"],
            "checks": v["checks"], "patterns": v.get("patterns") or [], "pack": v.get("pack"), "scorecards": v.get("scorecards") or [], "date": v["date_long"], "view": v["view"],
            "proof": [{k: x[k] for k in ("code", "name", "manager", "risk", "signs", "why", "selfie_url", "selfie_uri", "att_map", "eod_map",
                                          "att_time", "from_usual")} | {"matches": [{k: m[k] for k in ("name", "date", "url", "uri")} for m in x["matches"]]}
                      for x in v["proof"]]}
    js = json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
    ex = json.dumps({"highlights": v.get("highlights") or [], "data": v.get("data") or {}}, ensure_ascii=False, default=str, separators=(",", ":"))
    ex = ex.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
    from daily.branding import favicon_data_uri
    return _env.get_template("sales_dashboard.html").render(v=v, logo=logo_data_uri(), data_json=js, extra_json=ex,
                                                              favicon=favicon_data_uri("fs")).encode("utf-8")
