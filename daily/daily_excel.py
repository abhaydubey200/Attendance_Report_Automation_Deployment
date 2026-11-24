"""The daily Excel attachment: a small workbook in the same style as the month-end one.

    Summary          key figures vs the previous report day, key points, last 7 report days (+ chart)
    Teams            Director / HR only: one line per HOD's team, weakest first
    Needs attention  HOD / Director: everyone needing a look, with the action expected
    <one per action> HR only: not in master, routing problems, permissions pending, missing punches, absence streaks
    Team / Company list   everyone, people needing attention first
    Last 7 days      one row per person, one coloured cell per report day
    Trend            last 30 report days with a chart (working days)
    Last 30 days     one row per person: 30-day %, late, absent, usual in-time, and a coloured cell per day
    HOD scorecard    Director / HR only: each HOD's team over 30 days + weekday heat + chart
"""

from __future__ import annotations

import io
from datetime import date

import xlsxwriter

from core.config import Settings
from daily import analysis
from daily.branding import excel_banner
from database.models.daily import MailItem

CODES = [  # code, label, colour (cell), dark text?
    ("P", "Present", "#16a34a", False), ("LT", "Present, late", "#d97706", False), ("OD", "On duty", "#0d9488", False),
    ("WFH", "Work from home", "#4f46e5", False), ("HD", "Half day", "#f59e0b", False), ("L", "Leave", "#64748b", False),
    ("A", "Absent", "#dc2626", False), ("MP", "Missing punch", "#7c3aed", False), ("WO", "Week off", "#cbd5e1", True),
    ("HO", "Holiday", "#fcd34d", True), ("-", "Not tracked / no record", "#e2e8f0", True),
]
STATUS_CODE = {"PRESENT": "P", "MISSING_PUNCH": "MP", "ON_DUTY": "OD", "WFH": "WFH", "HALF_DAY": "HD", "LEAVE": "L",
               "ABSENT": "A", "WEEK_OFF": "WO", "HOLIDAY": "HO"}


def code_of(row: dict | None) -> str:
    if not row:
        return ""
    c = STATUS_CODE.get(row["status"], "-")
    return "LT" if c == "P" and "LATE" in (row.get("flags") or []) else c


def build(settings: Settings, item: MailItem, kind: str, s: dict, b: dict, ups: list[tuple[int, date]],
          grid: dict[str, dict[date, dict]], notes: dict[str, str], pack: dict | None = None) -> bytes:
    from daily.mail import ROSTER_COLS, _sort_attention_first, attention
    from daily.render import action_for

    buf = io.BytesIO()
    wb = xlsxwriter.Workbook(buf, {"in_memory": True, "strings_to_formulas": False, "strings_to_urls": False})
    border = {"border": 1, "border_color": "#E6E8EF", "valign": "vcenter"}
    head = wb.add_format({"bold": True, "font_color": "#FFFFFF", "bg_color": "#14213D", "text_wrap": True, "valign": "vcenter",
                          "border": 1, "border_color": "#14213D"})
    cell = wb.add_format(border)
    wrap = wb.add_format({**border, "text_wrap": True})
    bold = wb.add_format({**border, "bold": True, "font_color": "#14213D"})
    big = wb.add_format({**border, "bold": True, "font_size": 13, "font_color": "#14213D"})
    flag = wb.add_format({**border, "bg_color": "#FDECEC"})
    act = wb.add_format({"border": 1, "border_color": "#F5E3A6", "bg_color": "#FFF8E1", "text_wrap": True, "valign": "vcenter"})
    note = wb.add_format({"italic": True, "font_color": "#5D6577"})
    up_bad = wb.add_format({**border, "bold": True, "font_color": "#B91C1C"})
    up_good = wb.add_format({**border, "bold": True, "font_color": "#15803D"})
    pct_fmt = {k: wb.add_format({**border, "bold": True, "font_color": fc, "bg_color": bg})
               for k, fc, bg in (("good", "#15803D", "#F0FAF3"), ("warn", "#B45309", "#FFF8EB"), ("bad", "#B91C1C", "#FEF3F2"))}
    code_fmt = {c: wb.add_format({"align": "center", "valign": "vcenter", "bold": True, "font_size": 9, "border": 1, "border_color": "#FFFFFF",
                                  "bg_color": col, "font_color": "#334155" if dark else "#FFFFFF"}) for c, _, col, dark in CODES}
    code_fmt[""] = wb.add_format({"border": 1, "border_color": "#F1F5F9", "bg_color": "#F8FAFC"})

    def band(v):
        return "good" if v is not None and v >= 90 else "warn" if v is not None and v >= 75 else "bad"

    day = item.report_date.strftime(settings.app.date_format)
    who = {"hr": "HR action list", "director": "Company attendance"}.get(kind, "Team attendance")
    main = b["company"] if kind != "hod" else (b["team"] or b["summary"])
    prev = b.get("main_before") or {}

    # ------------------------------------------------------------------ Summary
    ws = wb.add_worksheet("Summary")
    widths = [30, 14, 14, 12, 3, 16, 14]
    for j, w in enumerate(widths):
        ws.set_column(j, j, w)
    excel_banner(wb, ws, widths, f"{who} - {day}", None if kind == "hr" else item.recipient_name)
    r = 3
    if main:
        for j, h in enumerate(("Key figures", day, b["previous_day"] or "Previous day", "Change")):
            ws.write(r, j, h, head)
        rows = [("Attendance %", "attendance_pct", False), ("People", "total", None), ("Present", "present", False), ("Absent", "absent", True),
                ("Late arrivals (counted present)", "late", True), ("Left early (counted present)", "left_early", True),
                ("Missing punch", "missing_punch", True), ("On leave", "leave", None), ("Work from home", "wfh", None), ("On duty", "od", None)]
        for i, (label, k, bad_up) in enumerate(rows, start=r + 1):
            v = main.get(k)
            p = prev.get(k)
            d = None if v is None or p is None else round(v - p, 1)
            ws.write(i, 0, label, bold)
            ws.write(i, 1, "-" if v is None else v, pct_fmt[band(v)] if k == "attendance_pct" else big)
            ws.write(i, 2, "" if p is None else p, cell)
            if d:
                ws.write(i, 3, f"{'+' if d > 0 else ''}{d:g}" + (" pts" if k == "attendance_pct" else ""),
                         (up_bad if (d > 0) == bad_up else up_good) if bad_up is not None else cell)
            else:
                ws.write(i, 3, "same" if d == 0 else "", cell)
        r += len(rows) + 2
    points = [x for x in (b.get("company_headline"), b.get("team_headline"), b.get("summary_headline")) if x]
    points += [c["text"] for c in b.get("concerns", [])]
    if kind == "hr":
        points.append(f"{b.get('hr_total', 0)} item(s) need HR action: {b.get('hr_summary') or 'none'}.")
    if b.get("pending"):
        points.append(f"{len(b['pending'])} short-leave request(s) waiting for approval.")
    if b.get("watch"):
        points.append(f"{len(b['watch'])} people to watch: a pattern is forming over the last report days.")
    if points:
        ws.merge_range(r, 0, r, 3, "Key points", head)
        for i, t in enumerate(points, start=r + 1):
            ws.merge_range(i, 0, i, 3, t, wrap)
            ws.set_row(i, 32 if len(t) > 70 else 18)
        r += len(points) + 2
    trend = b.get("trend") or []
    if trend:
        ws.write(r, 0, "Last report days", head)
        ws.write(r, 1, "Attendance %", head)
        ws.write(r, 2, "Absent", head)
        ws.write(r, 3, "Late", head)
        for i, t in enumerate(trend, start=r + 1):
            ws.write(i, 0, t["date"].strftime(settings.app.date_format + " (%a)"), cell)
            ws.write(i, 1, "off" if t["pct"] is None else t["pct"], pct_fmt[band(t["pct"])] if t["pct"] is not None else cell)
            ws.write(i, 2, t["absent"], cell)
            ws.write(i, 3, t["late"], cell)
        chart = wb.add_chart({"type": "column"})
        chart.add_series({"name": "Attendance %", "categories": ["Summary", r + 1, 0, r + len(trend), 0],
                          "values": ["Summary", r + 1, 1, r + len(trend), 1], "fill": {"color": "#16A34A"}, "gap": 50,
                          "data_labels": {"value": True, "num_format": "0", "font": {"size": 8}}})
        chart.set_title({"name": "Attendance % - last report days", "name_font": {"size": 11, "color": "#14213D"}})
        chart.set_legend({"none": True})
        chart.set_y_axis({"min": 0, "max": 100, "major_gridlines": {"visible": True, "line": {"color": "#E6E8EF"}}})
        chart.set_size({"width": 470, "height": 250})
        ws.insert_chart(3, 5, chart)
        r += len(trend) + 2
    ws.write(r, 0, "Late arrivals and early leavers are counted present. Attendance is a workforce-availability indicator, "
                   "not a measure of productivity.", note)

    # ------------------------------------------------------------------ Teams (Director / HR)
    if b.get("teams"):
        wt = wb.add_worksheet("Teams")
        cols = [("HOD's team", "name", 26), ("People", "people", 9), ("Attendance %", "pct", 13), ("Change (pts)", "change", 12),
                ("Absent", "absent", 9), ("Late", "late", 8), ("Missing punch", "missing_punch", 10), ("On leave", "leave", 9),
                ("Need attention", "attention", 11)]
        excel_banner(wb, wt, [w for _, _, w in cols], f"Attendance by HOD's team - {day}", "Weakest attendance first")
        for j, (h, _, w) in enumerate(cols):
            wt.write(3, j, h, head)
            wt.set_column(j, j, w)
        for i, t in enumerate(b["teams"], start=4):
            for j, (_, k, _) in enumerate(cols):
                v = t.get(k)
                fmt = pct_fmt[band(v)] if k == "pct" else (up_bad if v and v < 0 else up_good if v and v > 0 else cell) if k == "change" else cell
                wt.write(i, j, "" if v is None else v, fmt)
        wt.freeze_panes(4, 1)
        wt.autofilter(3, 0, 3 + len(b["teams"]), len(cols) - 1)

    # ------------------------------------------------------------------ Needs attention (HOD / Director)
    def detail_rows(rows: list[dict], cols: list[tuple[str, str, int]], name: str, title: str, sub: str | None = None,
                    empty: str = "Nothing to show.") -> None:
        w = wb.add_worksheet(name[:31])
        excel_banner(wb, w, [x for _, _, x in cols], title, sub)
        for j, (h, _, wd) in enumerate(cols):
            w.write(3, j, h, head)
            w.set_column(j, j, wd)
        for i, x in enumerate(rows, start=4):
            for j, (_, k, _) in enumerate(cols):
                v = x.get(k)
                w.write(i, j, "" if v is None else v, act if k == "action" else wrap if k in ("detail", "reason", "pattern") else cell)
        if not rows:
            w.write(4, 0, empty, note)
        else:
            w.autofilter(3, 0, 3 + len(rows), len(cols) - 1)
        w.freeze_panes(4, 2)

    def when(r: dict) -> str:
        i, o = analysis.t12(r.get("in_time")), analysis.t12(r.get("out_time"))
        if r.get("status") == "MISSING_PUNCH":
            return f"In {i} · no out-punch" if i and not o else f"Out {o} · no in-punch" if o and not i else "No punch time"
        return f"{i or '—'} – {o or '—'}" if i or o else ""

    if kind != "hr":
        base = s["company"] if kind == "director" else s["team"] + [x for x in s["summary"] if x["code"] not in {t["code"] for t in s["team"]}]
        need = []
        for x in _sort_attention_first(base):
            reason = attention(x)
            pending = "PERMISSION_PENDING" in x["flags"]
            if not reason and not pending:
                continue
            pat = notes.get(x["code"].upper())
            need.append({**x, "reason": reason or "Short leave requested - waiting for approval", "when": when(x),
                         "hours": analysis.hm(x.get("work_hours")) or "", "pattern": pat or "", "action": action_for(x, pat)})
        for w_ in b.get("watch", []):
            need.append({**w_, "reason": "Fine on the day", "when": when(w_), "hours": analysis.hm(w_.get("work_hours")) or "",
                         "pattern": w_["reason"], "action": w_["action"]})
        cols = [("Code", "code", 11), ("Name", "name", 24)] + ([("HOD", "hod", 20)] if kind == "director" else []) + [
            (day, "reason", 30), ("In – Out", "when", 22), ("Hours (h:mm)", "hours", 10), ("Recent pattern", "pattern", 30),
            ("Action required (manager)", "action", 44)]
        detail_rows(need, cols, "Needs attention", f"Needs attention - {day}",
                    "Absent, missing punch, late, left early, short leave waiting for approval, and patterns forming",
                    f"Nobody needs attention on {day}.")

    # ------------------------------------------------------------------ HR: one sheet per action
    if kind == "hr":
        names = {"not_in_master": "Not in master", "routing": "Routing problems", "permissions": "Permissions pending",
                 "onduty": "On duty pending",
                 "missing": "Missing punches", "streaks": "Absence streaks"}
        for g in b.get("hr_groups", []):
            rows = [{**x, "on_day": x.get("status_label") or "", "action": g["action"]} for x in g["rows"]]
            detail_rows(rows, [("Code", "code", 11), ("Name", "name", 24), ("HOD", "hod", 20), ("Details", "detail", 36),
                               (day, "on_day", 18), ("Action", "action", 44)],
                        names[g["key"]], f"{g['title']} - {day}", g["why"])

    # ------------------------------------------------------------------ full list
    def roster(name: str, rows: list[dict], heading: str, with_hod: bool) -> None:
        cols = ROSTER_COLS[:2] + ([("HOD", "hod", 20)] if with_hod else []) + ROSTER_COLS[2:]
        w = wb.add_worksheet(name[:31])
        excel_banner(wb, w, [x for _, _, x in cols], heading)
        for j, (h, _, wd) in enumerate(cols):
            w.write(2, j, h, head)
            w.set_column(j, j, wd)
        for i, x in enumerate(_sort_attention_first(rows), start=3):
            reason = attention(x)
            for j, (_, k, _) in enumerate(cols):
                v = (reason if k == "reason" else analysis.t12(x.get(k)) if k in ("in_time", "out_time")
                     else analysis.hm(x.get(k)) if k == "work_hours"
                     else analysis.mins_hm(x.get(k)) if k in ("late_minutes", "early_minutes") else x.get(k))
                blank = v in (None, 0) and k in ("late_minutes", "early_minutes", "in_time", "out_time", "work_hours", "leave_type", "reason",
                                                 "permission", "on_duty")
                w.write(i, j, "" if blank or v is None else v, flag if reason else cell)
        w.freeze_panes(3, 2)
        if rows:
            w.autofilter(2, 0, 2 + len(rows), len(cols) - 1)

    if kind == "hod":
        if s["team"]:
            roster("Team list", s["team"], f"{item.recipient_name} - team attendance - {day}", False)
        if s["summary"]:
            roster("Wider team list", s["summary"], f"Everyone under {item.recipient_name} - {day}", False)
        people = s["team"] + [x for x in s["summary"] if x["code"] not in {t["code"] for t in s["team"]}]
    else:
        roster("Company list", s["company"], f"Company attendance - {day}", True)
        people = s["company"]

    # ------------------------------------------------------------------ last 7 report days
    if ups and people:
        wl = wb.add_worksheet("Last 7 days")
        days = [d for _, d in ups]
        fixed = [("Code", 10), ("Name", 24)] + ([("HOD", 18)] if kind != "hod" else [])
        for j, (h, w) in enumerate(fixed):
            wl.write(0, j, h, head)
            wl.set_column(j, j, w)
        c0 = len(fixed)
        wl.set_row(0, 30)
        for j, d in enumerate(days, start=c0):
            wl.write(0, j, d.strftime("%d") + "\n" + d.strftime("%a"), head)
            wl.set_column(j, j, 6)
        wl.write(0, c0 + len(days), "Absent", head)
        wl.write(0, c0 + len(days) + 1, "Late", head)
        wl.set_column(c0 + len(days), c0 + len(days) + 1, 8)

        def score(p: dict) -> tuple:
            g = grid.get(p["code"].upper(), {})
            return (-sum(1 for d in days if code_of(g.get(d)) == "A"), -sum(1 for d in days if code_of(g.get(d)) in ("LT", "MP")), p["name"])

        ordered = sorted(people, key=score)
        for i, p in enumerate(ordered, start=1):
            g = grid.get(p["code"].upper(), {})
            wl.write(i, 0, p["code"], cell)
            wl.write(i, 1, p["name"], cell)
            if kind != "hod":
                wl.write(i, 2, p.get("hod") or "", cell)
            for j, d in enumerate(days, start=c0):
                c = code_of(g.get(d))
                wl.write(i, j, c, code_fmt.get(c, code_fmt["-"]) if c else code_fmt[""])
            wl.write(i, c0 + len(days), sum(1 for d in days if code_of(g.get(d)) == "A"), cell)
            wl.write(i, c0 + len(days) + 1, sum(1 for d in days if code_of(g.get(d)) == "LT"), cell)
        r = len(ordered) + 2
        wl.write(r, 1, "Key", bold)
        for k, (c, label, _, _) in enumerate(CODES, start=r + 1):
            wl.write(k, c0, c, code_fmt[c])
            wl.write(k, c0 + 1, label)
        wl.freeze_panes(1, c0)
        wl.autofilter(0, 0, len(ordered), c0 + len(days) + 1)

    # ------------------------------------------------------------------ last 30 days: trend (+ chart), grid, HOD scorecard (+ chart)
    if pack and pack["trend"] and people:
        P2X = {"P": "P", "M": "MP", "D": "OD", "W": "WFH", "H": "HD", "V": "L", "A": "A", "O": "WO", "N": "-", "-": ""}
        wt = wb.add_worksheet("Trend")
        excel_banner(wb, wt, [12, 8, 14, 9, 9], f"{who} – last {len(pack['trend'])} report days to {day}",
                     "Attendance % on working days (days when most people were on a week off / holiday are left out)")
        for j, (h, w) in enumerate([("Date", 12), ("Day", 8), ("Attendance %", 14), ("Absent", 9), ("Late", 9)]):
            wt.write(3, j, h, head)
            wt.set_column(j, j, w)
        for i, t in enumerate(pack["trend"], start=4):
            wt.write(i, 0, t["label"], cell)
            wt.write(i, 1, t["weekday"], cell)
            if t["pct"] is None:
                wt.write(i, 2, "week off / holiday", note)
            else:
                wt.write_number(i, 2, t["pct"], pct_fmt[band(t["pct"])])
            wt.write(i, 3, t["absent"], cell)
            wt.write(i, 4, t["late"], cell)
        last = 3 + len(pack["trend"])
        ch = wb.add_chart({"type": "line"})
        ch.add_series({"name": "Attendance %", "categories": ["Trend", 4, 0, last, 0], "values": ["Trend", 4, 2, last, 2],
                       "line": {"color": "#14213D", "width": 2.25}, "marker": {"type": "circle", "size": 5, "fill": {"color": "#F5B800"}}})
        colc = wb.add_chart({"type": "column"})
        colc.add_series({"name": "Absent", "categories": ["Trend", 4, 0, last, 0], "values": ["Trend", 4, 3, last, 3],
                         "fill": {"color": "#FCA5A5"}, "y2_axis": True})
        ch.combine(colc)
        ch.set_title({"name": "Attendance % and absent people", "name_font": {"size": 12}})
        ch.set_y_axis({"min": 40, "max": 100})
        ch.set_legend({"position": "bottom"})
        ch.set_size({"width": 760, "height": 340})
        wt.insert_chart(3, 6, ch)
        wt.freeze_panes(4, 1)

        w3 = wb.add_worksheet("Last 30 days")
        labels = pack["labels"]
        fixed = [("Code", 10), ("Name", 24)] + ([("HOD", 18)] if kind != "hod" else []) + \
                [("30-day %", 9), ("Late", 6), ("Absent", 7), ("Leave", 6), ("WFH / OD", 8), ("Usual in-time", 10), ("Avg hours", 8)]
        excel_banner(wb, w3, [w for _, w in fixed] + [4] * len(labels), f"{who} – day by day, last {len(labels)} report days to {day}",
                     "P present · LT late · OD on duty · WFH · HD half day · L leave · A absent · MP missing punch · WO week off / holiday")
        dh = wb.add_format({"bold": True, "font_color": "#FFFFFF", "bg_color": "#14213D", "align": "center", "rotation": 90, "border": 1, "font_size": 9})
        for j, (h, w) in enumerate(fixed):
            w3.write(3, j, h, head)
            w3.set_column(j, j, w)
        c0 = len(fixed)
        for k, (lab, wd) in enumerate(zip(labels, pack["weekday_of"])):
            w3.write(3, c0 + k, f"{lab} {wd}", dh)
        w3.set_column(c0, c0 + len(labels) - 1, 4.2)
        w3.set_row(3, 64)
        pp = pack["people"]
        ordered = sorted(people, key=lambda p: ((pp.get(p["code"].upper()) or {}).get("pct30") if (pp.get(p["code"].upper()) or {}).get("pct30") is not None else 999, p["name"]))
        for i, p in enumerate(ordered, start=4):
            h = pp.get(p["code"].upper()) or {}
            vals = [p["code"], p["name"]] + ([p.get("hod") or ""] if kind != "hod" else []) + \
                   [h.get("pct30"), h.get("late30"), h.get("absent30"), h.get("leave30"), h.get("wfh_od30"), h.get("usual_in"), h.get("avg_hours")]
            for j, x in enumerate(vals):
                w3.write(i, j, "" if x is None else x, pct_fmt[band(x)] if j == c0 - 7 and isinstance(x, (int, float)) else cell)
            for k, ch_ in enumerate((h.get("strip") or "-" * len(labels)).ljust(len(labels), "-")[:len(labels)]):
                c = P2X.get(ch_, "")
                w3.write(i, c0 + k, c, code_fmt.get(c, code_fmt[""]) if c else code_fmt[""])
        w3.autofilter(3, 0, 3 + len(ordered), c0 + len(labels) - 1)
        w3.freeze_panes(4, 2)

        if kind != "hod" and len(pack.get("groups") or []) > 1:
            g = pack["groups"]
            w4 = wb.add_worksheet("HOD scorecard")
            cols = [("HOD", 26), ("Last 30 days %", 13), ("Absent days (30)", 13)] + [(w, 6) for w in pack["weekdays"]]
            excel_banner(wb, w4, [w for _, w in cols], f"HOD teams – last 30 report days to {day}",
                         "Lowest first; weekday columns = attendance % on that weekday over the last 12 weeks")
            for j, (h, w) in enumerate(cols):
                w4.write(3, j, h, head)
                w4.set_column(j, j, w)
            for i, r_ in enumerate(g, start=4):
                w4.write(i, 0, r_["name"], bold)
                if r_["pct30"] is not None:
                    w4.write_number(i, 1, r_["pct30"], pct_fmt[band(r_["pct30"])])
                w4.write(i, 2, r_["absent30"], cell)
                for k, x in enumerate(r_["heat"]):
                    w4.write(i, 3 + k, "" if x is None else x, cell)
            w4.conditional_format(4, 3, 3 + len(g), 2 + len(pack["weekdays"]), {"type": "3_color_scale", "min_color": "#F8696B", "mid_color": "#FFEB84",
                                  "max_color": "#63BE7B", "min_type": "num", "min_value": 60, "mid_type": "num", "mid_value": 85, "max_type": "num", "max_value": 100})
            barc = wb.add_chart({"type": "bar"})
            barc.add_series({"name": "Last 30 days %", "categories": ["HOD scorecard", 4, 0, 3 + len(g), 0], "values": ["HOD scorecard", 4, 1, 3 + len(g), 1],
                             "fill": {"color": "#14213D"}, "data_labels": {"value": True, "num_format": "0.0"}})
            barc.set_title({"name": "Attendance by HOD team – last 30 report days", "name_font": {"size": 12}})
            barc.set_x_axis({"min": 50, "max": 100})
            barc.set_legend({"none": True})
            barc.set_size({"width": 620, "height": max(260, 26 * len(g) + 80)})
            w4.insert_chart(6 + len(g), 0, barc)
            w4.freeze_panes(4, 1)
    wb.close()
    return buf.getvalue()
