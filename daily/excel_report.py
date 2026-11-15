"""Excel report for one day and one audience (ALL, a Category or an HOD)."""

from __future__ import annotations

import io
from datetime import date

import xlsxwriter

from daily.analysis import STATUS_LABEL
from daily.render import breakdown, scope_label, scoped_rows, sources_label

BROWN, HONEY, CREAM, INK = "#835415", "#F5B800", "#FFF4E3", "#2B2118"
STATUS_FILL = {"PRESENT": "#E4F1E8", "MISSING_PUNCH": "#FFF1D6", "ON_DUTY": "#E8F0FB", "HALF_DAY": "#FFF8E1",
               "LEAVE": "#F3E8D9", "ABSENT": "#FBE4E1", "WEEK_OFF": "#EAF2F7", "WFH": "#E8F0FB", "NOT_TRACKED": "#EEEEEE"}

DETAIL_COLS = [("Code", "code", 12), ("Name", "name", 28), ("Category", "category", 12), ("Department", "department", 18),
               ("HOD", "hod", 18), ("Team", "team", 14), ("Reporting manager", "manager", 20), ("Status", "status_label", 15),
               ("In", "in_time", 8), ("Out", "out_time", 8), ("Hours", "work_hours", 8), ("Late (min)", "late_minutes", 10),
               ("Left early (min)", "early_minutes", 14), ("Leave type", "leave_type", 10), ("Source", "source", 12),
               ("Bizom", "bizom_status", 8), ("Designation", "designation", 12), ("Shift", "shift", 18)]


def build_excel(company: str, report_date: date, scope: str, insights: dict, rows: list[dict], date_format: str) -> bytes:
    data = insights["scopes"][scope]
    s, c = data["summary"], data["summary"]["counts"]
    rows = sorted(scoped_rows(rows, scope), key=lambda r: (r.get("department") or r["category"], r["code"]))
    title = f"{company} - Daily Attendance - {scope_label(scope)}"

    buf = io.BytesIO()
    wb = xlsxwriter.Workbook(buf, {"in_memory": True, "strings_to_formulas": False, "strings_to_urls": False})
    f_title = wb.add_format({"bold": True, "font_size": 16, "font_color": BROWN})
    f_sub = wb.add_format({"font_color": "#6E6152", "italic": True})
    f_head = wb.add_format({"bold": True, "font_color": "#FFFFFF", "bg_color": BROWN, "border": 1, "border_color": BROWN,
                            "text_wrap": True, "valign": "vcenter"})
    f_cell = wb.add_format({"border": 1, "border_color": "#ECDFC9"})
    f_label = wb.add_format({"bold": True, "bg_color": CREAM, "border": 1, "border_color": "#ECDFC9"})
    f_big = wb.add_format({"bold": True, "font_size": 14, "font_color": BROWN, "border": 1, "border_color": "#ECDFC9",
                           "align": "left"})
    f_section = wb.add_format({"bold": True, "font_size": 12, "font_color": BROWN, "bottom": 2, "bottom_color": HONEY})
    kind_fmt = {k: wb.add_format({"text_wrap": True, "valign": "top", "bg_color": bg, "border": 1, "border_color": "#ECDFC9"})
                for k, bg in {"good": "#E4F1E8", "warn": "#FFF1D6", "bad": "#FBE4E1", "info": "#F6ECDC"}.items()}
    status_fmt = {k: wb.add_format({"bg_color": v, "border": 1, "border_color": "#ECDFC9"}) for k, v in STATUS_FILL.items()}

    # ---- Summary
    ws = wb.add_worksheet("Summary")
    ws.set_column(0, 0, 30)
    ws.set_column(1, 6, 16)
    ws.write(0, 0, title, f_title)
    ws.write(1, 0, f"Date: {report_date.strftime(date_format)}   |   Generated automatically from {sources_label(insights)}", f_sub)
    kpis = [("Employees", s["employees"]), ("Tracked", s["tracked"]), ("Attendance %", "" if s["attendance_pct"] is None else s["attendance_pct"]),
            ("Present", c["PRESENT"]), ("Absent", c["ABSENT"]), ("Late arrivals", s["late"]), ("Missing punch", c["MISSING_PUNCH"]),
            ("Leave", c["LEAVE"]), ("Half day", c["HALF_DAY"]), ("On duty", c["ON_DUTY"]), ("Work from home", c.get("WFH", 0)), ("Left early", s["left_early"]),
            ("Week off", c.get("WEEK_OFF", 0)), ("Not tracked", c["NOT_TRACKED"]), ("Average arrival", s["avg_in_time"] or "-"),
            ("Average working hours", s["avg_work_hours"] if s["avg_work_hours"] is not None else "-")]
    ws.write(3, 0, "Key figures", f_section)
    for i, (k, v) in enumerate(kpis):
        ws.write(4 + i, 0, k, f_label)
        ws.write(4 + i, 1, v, f_big)
    r = 5 + len(kpis)
    ws.write(r, 0, "Highlights", f_section)
    for i, h in enumerate(data["highlights"]):
        ws.merge_range(r + 1 + i, 0, r + 1 + i, 6, h["text"], kind_fmt[h["kind"]])
        ws.set_row(r + 1 + i, 30)
    r = r + 2 + len(data["highlights"])
    bd = breakdown(insights, scope)
    if bd["rows"]:
        ws.set_column(7, 8, 14)
        ws.write(r, 0, f"By {bd['by'].lower()}", f_section)
        head = [bd["by"], "HOD", "Employees", "Attendance %", "Present", "Absent", "Late", "Leave", "Not tracked"]
        for j, h in enumerate(head):
            ws.write(r + 1, j, h, f_head)
        for i, x in enumerate(bd["rows"]):
            vals = [x["name"], x.get("hod") or "", x["employees"], "" if x["attendance_pct"] is None else x["attendance_pct"],
                    x["present"], x["absent"], x["late"], x["leave"], x["not_tracked"]]
            for j, v in enumerate(vals):
                ws.write(r + 2 + i, j, v, f_cell)
        r = r + 3 + len(bd["rows"])
    rules = insights["rules"]
    ws.write(r, 0, "How this is counted", f_section)
    notes = [f"Late = first punch after {rules['late_after']}; left early = last punch before {rules['early_before']}.",
             f"Attendance % = (present + on duty + {'missing punch + ' if rules['single_punch_counts_present'] else ''}half of half-days) / tracked employees.",
             "Not tracked = no punch and no shift assigned (not counted in attendance %)." if rules["no_punch_no_shift"] == "NOT_TRACKED"
             else "No punch counts as absent.",
             "Sources: Pocket HRMS punches and leave first; with no punch, the Bizom status is used (P present, A absent, WO week off "
             "- not counted in attendance %, other codes leave). Present in either source counts as present.",
             f"On-duty codes: {', '.join(rules['on_duty_codes']) or 'none'}; other leave codes count as leave."]
    for i, n in enumerate(notes):
        ws.write(r + 1 + i, 0, n, f_sub)

    # ---- detail sheets
    def sheet(name: str, subset: list[dict], extra_sort=None):
        w = wb.add_worksheet(name[:31])
        for j, (h, _, width) in enumerate(DETAIL_COLS):
            w.write(0, j, h, f_head)
            w.set_column(j, j, width)
        data_rows = sorted(subset, key=extra_sort) if extra_sort else subset
        for i, row in enumerate(data_rows, start=1):
            for j, (_, key, _) in enumerate(DETAIL_COLS):
                v = row.get(key)
                fmt = status_fmt.get(row["status"], f_cell) if key == "status_label" else f_cell
                w.write(i, j, "" if v is None else v, fmt)
        if not data_rows:
            w.write(1, 0, "None", f_cell)
        w.freeze_panes(1, 2)
        if data_rows:
            w.autofilter(0, 0, len(data_rows), len(DETAIL_COLS) - 1)

    sheet("All Employees", rows)
    sheet("Absent", [x for x in rows if x["status"] == "ABSENT"])
    sheet("Late Arrivals", [x for x in rows if "LATE" in x["flags"]], lambda x: -x["late_minutes"])
    sheet("Left Early", [x for x in rows if "LEFT_EARLY" in x["flags"]], lambda x: -x["early_minutes"])
    sheet("Missing Punch", [x for x in rows if x["status"] == "MISSING_PUNCH"])
    sheet("Leave, On Duty, Week Off", [x for x in rows if x["status"] in ("LEAVE", "HALF_DAY", "ON_DUTY", "WFH", "WEEK_OFF")])
    sheet("Short Hours", [x for x in rows if "SHORT_HOURS" in x["flags"]], lambda x: x["work_hours"] or 0)
    sheet("Not Tracked", [x for x in rows if x["status"] == "NOT_TRACKED"])
    wb.close()
    return buf.getvalue()


__all__ = ["build_excel", "STATUS_LABEL"]
