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


def _person(r) -> dict:
    flags = [f for f in (r.flags or "").split(",") if f]
    return {"code": r.code, "name": r.name, "designation": r.designation or "", "zone": r.zone or "", "manager": manager_label(r.manager_name),
            "zonal": r.zonal_name or "", "hod": r.hod_name or "", "status": r.status, "status_label": STATUS_LABEL.get(r.status, r.status),
            "not_marked": r.status == "ABSENT" and not r.bizom_status, "leave": r.leave_type or "",
            "att": t12(r.attendance_time) or "", "first": t12(r.first_activity) or "", "last": t12(r.last_activity) or "",
            "market": hm(r.market_minutes), "market_min": r.market_minutes, "km": r.km, "eod": t12(r.eod_time) or "",
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
    }
    pat = (ctx or {}).get("patterns") or {}
    lv = ("high", "medium", "low")
    out["patterns"] = sorted([{"code": p["code"], "name": p["name"], "designation": p["designation"], "manager": p["manager"],
                               "status_label": p["status_label"], "patterns": pat[p["code"]]} for p in people if p["code"] in pat],
                             key=lambda x: (lv.index(x["patterns"][0]["level"]), -len(x["patterns"]), x["name"]))
    for p in people:
        p["patterns"] = pat.get(p["code"], [])
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
    lines += ["Full lists, selfies and map links: the attached dashboard (open in Chrome or Edge) and Excel.",
              "Warning signs are for checking, not proof. Automated email from the APIS HR Portal (source: Bizom)."]
    return "\n".join(lines)


# ---------------------------------------------------------------- Excel
def excel(v: dict) -> bytes:
    buf = io.BytesIO()
    wb = xlsxwriter.Workbook(buf, {"in_memory": True, "strings_to_formulas": False, "strings_to_urls": False})
    head = wb.add_format({"bold": True, "font_color": "#FFFFFF", "bg_color": "#14213D", "text_wrap": True, "valign": "vcenter", "border": 1})
    cell = wb.add_format({"border": 1, "border_color": "#E6E8EF", "valign": "vcenter"})
    wrap = wb.add_format({"border": 1, "border_color": "#E6E8EF", "valign": "vcenter", "text_wrap": True})
    big = wb.add_format({"border": 1, "border_color": "#E6E8EF", "bold": True, "font_size": 13, "font_color": "#14213D"})
    bold = wb.add_format({"border": 1, "border_color": "#E6E8EF", "bold": True, "font_color": "#14213D"})
    note = wb.add_format({"italic": True, "font_color": "#5D6577"})
    lvl = {k: wb.add_format({"border": 1, "border_color": "#E6E8EF", "bold": True, "font_color": c, "bg_color": b})
           for k, c, b in (("high", "#B91C1C", "#FEF3F2"), ("medium", "#B45309", "#FFF8EB"), ("low", "#475569", "#F1F5F9"))}
    st = {k: wb.add_format({"border": 1, "border_color": "#E6E8EF", "bold": True, "font_color": c}) for k, c in COLORS.items()}

    ws = wb.add_worksheet("Summary")
    excel_banner(wb, ws, [32, 14, 14, 14], f"Field sales attendance - {v['date_long']} - {v['recipient']}")
    ws.set_column(0, 0, 36)
    ws.set_column(1, 3, 14)
    kpis = [("People", v["n"]), ("Attendance %", v["pct"] if v["pct"] is not None else "-")] + \
           [(v["status_label"][k], v["counts"][k]) for k in v["counts"]] + [("Need checking", len(v["flagged"])),
                                                                            ("Need checking - serious", v["flagged_high"])]
    for i, (k, val) in enumerate(kpis, start=3):
        ws.write(i, 0, k, bold)
        ws.write(i, 1, val, big)
    r = 4 + len(kpis)
    if v["warnings"]:
        ws.write(r, 0, "Warning sign", head)
        ws.write(r, 1, "People", head)
        ws.write(r, 2, "Level", head)
        for i, w in enumerate(v["warnings"], start=r + 1):
            ws.write(i, 0, w["label"], cell)
            ws.write(i, 1, w["n"], cell)
            ws.write(i, 2, w["level"], lvl[w["level"]])
        r += 2 + len(v["warnings"])
    ws.write(r, 0, "Warning signs are for checking with the person, not proof of anything.", note)

    if v["teams"]:
        wt = wb.add_worksheet("By team")
        cols = [("HOD", "hod", 22), ("Zonal head", "zonal", 24), ("People", "people", 9), ("Attendance %", "pct", 12),
                ("Absent", "absent", 9), ("Late", "late", 8), ("Need checking", "flagged", 12)]
        for j, (h, _, w) in enumerate(cols):
            wt.write(0, j, h, head)
            wt.set_column(j, j, w)
        for i, t in enumerate(v["teams"], start=1):
            for j, (_, k, _) in enumerate(cols):
                wt.write(i, j, "" if t[k] is None else t[k], cell)
        wt.freeze_panes(1, 0)

    wf = wb.add_worksheet("Needs checking")
    cols = [("Code", 10), ("Name", 26), ("Designation", 12), ("Manager", 22), ("Warning signs", 46), ("Evidence", 60)]
    for j, (h, w) in enumerate(cols):
        wf.write(0, j, h, head)
        wf.set_column(j, j, w)
    for i, p in enumerate(v["flagged"], start=1):
        top = min((f["level"] for f in p["flags"]), key=lambda x: ("high", "medium", "low").index(x))
        for j, val in enumerate([p["code"], p["name"], p["designation"], p["manager"], "; ".join(f["label"] for f in p["flags"]), p["evidence"]]):
            wf.write(i, j, val, lvl[top] if j == 4 else wrap)
    if not v["flagged"]:
        wf.write(1, 0, "Nothing to check on this day.", note)
    wf.freeze_panes(1, 2)

    if v.get("patterns"):
        wpat = wb.add_worksheet("Patterns")
        cols = [("Code", 10), ("Name", 26), ("Designation", 11), ("Manager", 22), ("Status on the day", 13), ("Pattern", 34),
                ("Proof (from the uploaded days)", 90)]
        for j, (h, w) in enumerate(cols):
            wpat.write(0, j, h, head)
            wpat.set_column(j, j, w)
        i = 1
        for x in v["patterns"]:
            for p in x["patterns"]:
                for j, val in enumerate([x["code"], x["name"], x["designation"], x["manager"], x["status_label"], p["label"], p["text"]]):
                    wpat.write(i, j, val, lvl[p["level"]] if j == 5 else wrap)
                i += 1
        wpat.write(i + 1, 0, "Each pattern is a count over the person's own uploaded working days (week offs, leave and days "
                             "without an upload are not counted); the dates are listed so each one can be checked in Bizom.", note)
        wpat.autofilter(0, 0, max(1, i - 1), len(cols) - 1)
        wpat.freeze_panes(1, 2)

    if v["checks"]:
        wc = wb.add_worksheet("Location & selfie checks")
        cols = [("Risk (0-100)", 9), ("Code", 10), ("Name", 26), ("Designation", 11), ("Manager", 22), ("Type", 10), ("Warning sign", 34), ("Why", 70)]
        for j, (h, w) in enumerate(cols):
            wc.write(0, j, h, head)
            wc.set_column(j, j, w)
        i = 1
        for c in v["checks"]:
            for s in c["signs"]:
                for j, val in enumerate([c["risk"], c["code"], c["name"], c["designation"], c["manager"], s["kind"], s["label"], s["why"]]):
                    wc.write(i, j, val, lvl[s["level"]] if j == 6 else wrap)
                i += 1
        wc.write(i + 1, 0, "Risk = all warning signs of the day weighted by level, plus how unusual the day is for the person (learned model). "
                           "Map and selfies: HR Portal > Field Sales > Needs checking.", note)
        wc.autofilter(0, 0, max(1, i - 1), len(cols) - 1)
        wc.freeze_panes(1, 3)

    if v["proof"]:
        wp = wb.add_worksheet("Proof")
        link = wb.add_format({"font_color": "#1D4ED8", "underline": 1, "valign": "top", "text_wrap": True})
        top = wb.add_format({"border": 1, "border_color": "#E6E8EF", "valign": "top", "text_wrap": True})
        cols = [("Risk", 6), ("Employee", 24), ("Warning signs and why", 52), ("Attendance selfie", 17), ("Matching selfie", 17), ("Where", 30)]
        for j, (h, w) in enumerate(cols):
            wp.write(0, j, h, head)
            wp.set_column(j, j, w)
        for i, x in enumerate(v["proof"], start=1):
            wp.set_row(i, 132)
            wp.write(i, 0, x["risk"], top)
            wp.write(i, 1, f"{x['name']}\n{x['code']}\n{x['manager']}", top)
            wp.write(i, 2, "\n".join(f"{s['kind']}: {s['label']}" for s in x["signs"]) + ("\n\n" + x["why"] if x["why"] else ""), top)
            for j, (jpg, url, cap) in enumerate([(x["selfie_jpg"], x["selfie_url"], f"{v['date_long']}")] +
                                                [(m["jpg"], m["url"], f"{m['name']} {m['date']}") for m in x["matches"][:1]], start=3):
                if jpg:
                    wp.insert_image(i, j, f"{cap}.jpg", {"image_data": io.BytesIO(jpg), "x_scale": 0.52, "y_scale": 0.52,
                                                         "x_offset": 4, "y_offset": 4, "url": url, "object_position": 1})
                elif url:
                    wp.write_url(i, j, url, link, "Open selfie")
            r_lines = [x["from_usual"]] if x["from_usual"] else []
            wp.write(i, 5, "\n".join(r_lines) or "", top)
            if x["att_map"]:
                wp.write_url(i, 5, x["att_map"], link, ("\n".join(r_lines) + "\n" if r_lines else "") + "Attendance place on the map")
        wp.write(len(v["proof"]) + 2, 0, "Selfies are small copies made for this workbook; click one to open the original on Bizom. "
                                         "The HR Portal itself keeps no photos.", note)
        wp.freeze_panes(1, 2)

    wn = wb.add_worksheet("Absent")
    for j, (h, w) in enumerate([("Code", 10), ("Name", 28), ("Designation", 12), ("Zone", 12), ("Manager", 24), ("Reason", 36)]):
        wn.write(0, j, h, head)
        wn.set_column(j, j, w)
    for i, p in enumerate(v["not_marked"], start=1):
        for j, val in enumerate([p["code"], p["name"], p["designation"], p["zone"], p["manager"],
                                 "Did not mark attendance in Bizom" if p["not_marked"] else "Marked absent in Bizom"]):
            wn.write(i, j, val, cell)

    wl = wb.add_worksheet("Team list")
    cols = [("Code", "code", 10), ("Name", "name", 26), ("Designation", "designation", 11), ("Zone", "zone", 10), ("Manager", "manager", 22),
            ("Status", "status_label", 10), ("Leave", "leave", 14), ("Attendance time", "att", 11), ("First activity", "first", 11),
            ("Last activity", "last", 11), ("Time in market (h:mm)", "market", 11), ("KM", "km", 8), ("Day end", "eod", 10),
            ("Calls", "calls", 7), ("Productive", "productive", 9), ("Order value", "order_value", 11), ("Warning signs", "warn", 40)]
    if v["view"] != "team":
        cols.insert(5, ("HOD", "hod", 18))
    for j, (h, _, w) in enumerate(cols):
        wl.write(0, j, h, head)
        wl.set_column(j, j, w)
    for i, p in enumerate(v["people"], start=1):
        for j, (_, k, _) in enumerate(cols):
            val = "; ".join(f["label"] for f in p["flags"]) if k == "warn" else p.get(k)
            wl.write(i, j, "" if val is None else val, st.get(p["status"], cell) if k == "status_label" else cell)
    wl.autofilter(0, 0, len(v["people"]), len(cols) - 1)
    wl.freeze_panes(1, 2)

    if v["view"] == "hr" and v["data"]:
        wd = wb.add_worksheet("Data issues")
        wd.set_column(0, 0, 60)
        r = 0
        for title, items in (("In Bizom but not on the field sales staff list", v["data"].get("not_in_staff_list", [])),
                             ("Marked attendance in Bizom but Left on the staff list", v["data"].get("left_but_marked", []))):
            wd.write(r, 0, f"{title} ({len(items)})", head)
            for i, x in enumerate(items, start=r + 1):
                wd.write(i, 0, x, cell)
            r += 2 + len(items)
        wd.write(r, 0, f"'Not Marked' in the EOD report: {v['data'].get('eod_not_marked', 0)} users (names only - Bizom gives no code)", note)
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
