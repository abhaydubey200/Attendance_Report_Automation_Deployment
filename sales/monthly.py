"""Field Sales month-end report: one email per recipient (same routing as the daily emails) with an Excel workbook and a
dashboard. Short email, details in the attachments (same approach as Module 1's approved month-end). The key sales part:
people whose warning signs REPEAT (on 3+ days) - one bad day is noise, a repeat is a pattern to discuss."""

from __future__ import annotations

import calendar
import io
import json
from collections import Counter, defaultdict
from datetime import date, timedelta

import xlsxwriter
from sqlalchemy import select
from sqlalchemy.orm import Session

from core.config import Settings
from daily.branding import excel_banner, favicon_data_uri, logo_data_uri
from daily.mailer import Attachment
from database.connection import session_scope
from database.models.sales import SalesDayUpload, SalesEmployee, SalesEmployeeDay, SalesJobRun, SalesMailItem
from sales import jobs, routing
from sales.analysis import STATUS_LABEL, WARNINGS
from sales.config import get_email
from sales.report import COLORS, _env, hm

PREFIX = "MONTHLY:"
ABSENT_DAYS, LATE_DAYS, REPEAT_DAYS = 3, 5, 3
PERFECT_MIN_DAYS = 5          # "full attendance" means something only over enough uploaded days
CODE = {"PRESENT": "P", "LATE": "LT", "HALF_DAY": "HD", "LEAVE": "L", "WEEK_OFF": "WO", "ABSENT": "A"}
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def bounds(month: str) -> tuple[date, date]:
    y, m = (int(x) for x in month.split("-"))
    return date(y, m, 1), date(y, m, calendar.monthrange(y, m)[1])


def label(month: str) -> str:
    return bounds(month)[0].strftime("%b-%Y")


def previous_month(today: date | None = None) -> str:
    first = (today or jobs.yesterday_ist() + timedelta(days=1)).replace(day=1)
    return (first - timedelta(days=1)).strftime("%Y-%m")


def _month_rows(session: Session, month: str) -> list[tuple[date, SalesEmployeeDay]]:
    start, end = bounds(month)
    return list(session.execute(
        select(SalesDayUpload.report_date, SalesEmployeeDay).join(SalesDayUpload, SalesDayUpload.upload_id == SalesEmployeeDay.upload_id)
        .where(SalesDayUpload.is_current.is_(True), SalesDayUpload.report_date >= start, SalesDayUpload.report_date <= end)
        .order_by(SalesDayUpload.report_date)).all())


def _pct(c: Counter) -> float | None:
    due = sum(c.values()) - c["WEEK_OFF"]
    return round(100 * (c["PRESENT"] + c["LATE"] + 0.5 * c["HALF_DAY"]) / due, 1) if due else None


def build_view(session: Session, month: str, codes: set[str] | None, view: str, recipient: str) -> dict:
    rows = [(d, r) for d, r in _month_rows(session, month) if codes is None or r.code in codes]
    staff = {e.code: e for e in session.scalars(select(SalesEmployee))}
    days = sorted({d for d, _ in rows})
    people: dict[str, dict] = {}
    total, week_c, week_flag = Counter(), defaultdict(Counter), Counter()
    for d, r in rows:
        p = people.setdefault(r.code, {"code": r.code, "name": r.name, "designation": r.designation or "", "zone": r.zone or "",
                                       "team_head": (staff[r.code].manager_name if r.code in staff else None) or "", "hod": r.hod_name or "",
                                       "c": Counter(), "flags": Counter(), "flag_days": 0, "cal": {}, "market": []})
        fl = [f for f in (r.flags or "").split(",") if f]
        p["c"][r.status] += 1
        p["flags"].update(fl)
        p["flag_days"] += bool(fl)
        p["cal"][d.isoformat()] = CODE.get(r.status, "") + ("!" if fl else "")
        if r.market_minutes is not None:
            p["market"].append(r.market_minutes)
        total[r.status] += 1
        wk = d - timedelta(days=d.weekday())
        week_c[wk][r.status] += 1
        week_flag[wk] += bool(fl)
    out = []
    for p in people.values():
        c, fl, mk = p.pop("c"), p.pop("flags"), p.pop("market")
        repeat = [WARNINGS[k][0] for k, n in fl.most_common() if n >= REPEAT_DAYS and k in WARNINGS]
        reasons = ([f"{c['ABSENT']} absent days"] if c["ABSENT"] >= ABSENT_DAYS else []) + \
                  ([f"{c['LATE']} late days"] if c["LATE"] >= LATE_DAYS else []) + [f"{w} (repeated)" for w in repeat]
        out.append({**p, "days": sum(c.values()), **{k.lower(): c[k] for k in STATUS_LABEL}, "pct": _pct(c), "repeat": repeat,
                    "reasons": reasons, "avg_market": hm(round(sum(mk) / len(mk))) if mk else "",
                    "warnings": [{"label": WARNINGS[k][0], "level": WARNINGS[k][1], "days": n} for k, n in fl.most_common() if k in WARNINGS],
                    "perfect": c["PRESENT"] > 0 and not (c["ABSENT"] or c["LATE"] or c["HALF_DAY"] or c["LEAVE"]) and p["flag_days"] == 0})
    from sales import checks
    start_m, end_m = bounds(month)
    pat = checks.month_patterns(session, start_m, end_m, codes, REPEAT_DAYS)
    for p in out:
        x = pat.get(p["code"])
        p["checks"] = x or {"location_days": 0, "selfie_days": 0, "unusual_days": 0, "max_risk": 0, "top": [], "reasons": []}
        p["reasons"] += [r for r in p["checks"]["reasons"]]
        if p["checks"]["reasons"]:
            p["perfect"] = False
    # scorecard comparison: the same person's attendance % in the month before
    y, mth = int(month[:4]), int(month[5:7])
    prev = f"{y - 1}-12" if mth == 1 else f"{y}-{mth - 1:02d}"
    pc: dict[str, Counter] = defaultdict(Counter)
    for _, r in _month_rows(session, prev):
        if codes is None or r.code in codes:
            pc[r.code][r.status] += 1
    for p in out:
        p["prev_pct"] = _pct(pc[p["code"]]) if p["code"] in pc else None
        p["change"] = round(p["pct"] - p["prev_pct"], 1) if p["pct"] is not None and p["prev_pct"] is not None else None
    out.sort(key=lambda p: (-len(p["reasons"]), -p["absent"], -p["flag_days"], p["name"]))
    weeks = []
    for n, (wk, c) in enumerate(sorted(week_c.items()), start=1):
        in_month = [d for d in days if wk <= d <= wk + timedelta(days=6)]
        weeks.append({"week": f"Week {n}", "range": f"{in_month[0]:%d %b} – {in_month[-1]:%d %b}", "pct": _pct(c), "absent": c["ABSENT"],
                      "late": c["LATE"], "flagged": week_flag[wk]})
    teams = []
    # teams: every view (the email shows the table only when there is more than one team)
    g = defaultdict(Counter)
    gp = defaultdict(set)
    for d, r in rows:
        th = (staff[r.code].manager_name if r.code in staff else None) or "No team head"
        g[(r.hod_name or "No HOD", th)][r.status] += 1
        gp[(r.hod_name or "No HOD", th)].add(r.code)
    for (hod, th), c in sorted(g.items(), key=lambda kv: (_pct(kv[1]) or 999)):
        teams.append({"hod": hod, "team_head": th, "people": len(gp[(hod, th)]), "pct": _pct(c), "absent": c["ABSENT"], "late": c["LATE"]})
    # daily trend (Sundays / holidays - most people off - left out) and the team-head scorecard with last month and weekdays
    per_day: dict[date, Counter] = defaultdict(Counter)
    for d, r in rows:
        per_day[d][r.status] += 1
    off = {d for d, c in per_day.items() if c["WEEK_OFF"] > 0.5 * sum(c.values())}
    trend = [{"date": d.isoformat(), "label": f"{d.day}-{d:%b}", "weekday": f"{d:%a}", "pct": None if d in off else _pct(per_day[d]),
              "off_day": d in off, "absent": per_day[d]["ABSENT"], "late": per_day[d]["LATE"], "off": per_day[d]["WEEK_OFF"]} for d in days]
    th_of = {r.code: ((staff[r.code].manager_name if r.code in staff else None) or "No team head") for _, r in rows}
    th_c: dict[str, Counter] = defaultdict(Counter)
    th_w: dict[str, list[Counter]] = defaultdict(lambda: [Counter() for _ in range(7)])
    for d, r in rows:
        if d in off:
            continue
        th_c[th_of[r.code]][r.status] += 1
        th_w[th_of[r.code]][d.weekday()][r.status] += 1
    prev_c: dict[str, Counter] = defaultdict(Counter)
    for d, r in _month_rows(session, prev):
        if codes is None or r.code in codes:
            prev_c[(staff[r.code].manager_name if r.code in staff else None) or "No team head"][r.status] += 1
    by_th: dict[str, list[dict]] = defaultdict(list)
    for p in out:
        by_th[p["team_head"] or "No team head"].append(p)
    scorecards = []
    for th, ps in by_th.items():
        c = th_c[th]
        worked = c["PRESENT"] + c["LATE"] + c["HALF_DAY"]
        pc, pp = _pct(c), _pct(prev_c[th]) if prev_c.get(th) else None
        ranked = sorted((p for p in ps if p["pct"] is not None), key=lambda p: (p["pct"], p["name"]))
        scorecards.append({"team_head": th, "people": len(ps), "pct": pc, "prev_pct": pp,
                           "change": round(pc - pp, 1) if pc is not None and pp is not None else None,
                           "late_pct": round(100 * c["LATE"] / worked, 1) if worked else None, "absent": c["ABSENT"],
                           "attention": sum(1 for p in ps if p["reasons"]), "perfect": sum(1 for p in ps if p["perfect"]),
                           "heat": [_pct(w) for w in th_w[th]], "lowest": [f"{p['name']} ({p['pct']:g}%)" for p in ranked[:3]]})
    scorecards.sort(key=lambda r: (r["pct"] if r["pct"] is not None else 999, r["team_head"]))
    safe = "".join(ch if ch.isalnum() else "_" for ch in recipient).strip("_")
    return {"trend": trend, "scorecards": scorecards, "weekdays": ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"], "prev_label": label(prev),
            "view": view, "recipient": recipient, "month": month, "month_long": bounds(month)[0].strftime("%B %Y"), "label": label(month),
            "days": [d.isoformat() for d in days], "work_days": len(days), "people": out, "n": len(out), "pct": _pct(total),
            "absent": total["ABSENT"], "late": total["LATE"], "leave": total["LEAVE"], "flag_days": sum(p["flag_days"] for p in out),
            "attention": [p for p in out if p["reasons"]], "perfect": [p for p in out if p["perfect"]] if len(days) >= PERFECT_MIN_DAYS else [], "weeks": weeks, "teams": teams,
            "title": {"team": "Monthly Field Sales Attendance", "company": "Monthly Field Sales Attendance – Company",
                      "hr": "Monthly Field Sales – HR"}[view], "thresholds": {"absent": ABSENT_DAYS, "late": LATE_DAYS, "repeat": REPEAT_DAYS},
            "stem": f"Field_Sales_Monthly_{month}_{safe}", "colors": COLORS}


def generate(settings: Settings, engine, month: str | None = None, trigger: str = "MANUAL", actor: str = "admin") -> dict:
    month = month or previous_month()
    with jobs.job_lock(settings, "sales_monthly"):
        with session_scope(engine) as s:
            run_id = jobs.start(s, "MONTHLY", month, trigger, actor).id
        with session_scope(engine) as s:
            rows = _month_rows(s, month)
            if not rows:
                res = {"month": month, "problem": f"No Field Sales days uploaded in {label(month)}."}
                jobs.finish(s, s.get(SalesJobRun, run_id), jobs.FAILED, res, res["problem"])
                return {"run_id": run_id, "status": jobs.FAILED, **res}
            start, end = bounds(month)
            last_upload = s.scalar(select(SalesDayUpload.upload_id).where(SalesDayUpload.is_current.is_(True),
                                   SalesDayUpload.report_date >= start, SalesDayUpload.report_date <= end).order_by(SalesDayUpload.report_date.desc()))
            cfg = get_email(s)
            staff = {e.code: e for e in s.scalars(select(SalesEmployee))}
            codes = {r.code for _, r in rows}
            for old in s.scalars(select(SalesMailItem).where(SalesMailItem.report_date == end, SalesMailItem.recipient_key.like(f"{PREFIX}%"),
                                                             SalesMailItem.status.in_(("PENDING", "HELD", "FAILED", "DUPLICATE")))):
                old.status, old.note = "SUPERSEDED", "Replaced by a newer month-end run."
            delivered = {k for (k,) in s.execute(select(SalesMailItem.recipient_key).where(
                SalesMailItem.report_date == end, SalesMailItem.status.in_(("SENT", "SAVED", "TEST_SENT"))))}
            made = Counter()
            for rec in routing.recipients(codes, staff, cfg):
                key = f"{PREFIX}{rec.key}"
                status, note = rec.status, rec.note
                if status == "HELD" and cfg.test_recipient:
                    status, note = "PENDING", f"Testing: {rec.note}"
                if status == "PENDING" and key in delivered:
                    status, note = "DUPLICATE", "Month-end report already sent."
                v = build_view(s, month, rec.codes, rec.view, rec.name)
                s.add(SalesMailItem(upload_id=last_upload, report_date=end, recipient_key=key[:200], recipient_name=rec.name[:200],
                                    role=f"Month-end · {rec.role}", to_addrs=", ".join(rec.to) or None,
                                    subject=f"Field Sales Monthly Attendance | {label(month)} | {rec.name}"[:300],
                                    content=json.dumps({"kind": "monthly", "month": month, "codes": sorted(rec.codes), "view": rec.view}),
                                    counts=json.dumps({"people": v["n"], "absent": v["absent"], "late": v["late"], "flagged": len(v["attention"]),
                                                       "attendance_pct": v["pct"]}), status=status, note=note, attempts=0))
                made[status] += 1
            s.flush()
            res = {"month": month, "days": len({d for d, _ in rows}), "people": len(codes), "emails": dict(made)}
            jobs.finish(s, s.get(SalesJobRun, run_id), jobs.SUCCESS, res)
    return {"run_id": run_id, "status": jobs.SUCCESS, **res}


def items(session: Session, month: str) -> list[SalesMailItem]:
    end = bounds(month)[1]
    return list(session.scalars(select(SalesMailItem).where(SalesMailItem.report_date == end, SalesMailItem.recipient_key.like(f"{PREFIX}%"),
                                                            SalesMailItem.status != "SUPERSEDED").order_by(SalesMailItem.id)))


def months(session: Session) -> list[dict]:
    out = {}
    for d, in session.execute(select(SalesDayUpload.report_date).where(SalesDayUpload.is_current.is_(True))):
        m = d.strftime("%Y-%m")
        out[m] = out.get(m, 0) + 1
    return [{"month": m, "label": label(m), "days": n, "emails": len(items(session, m))} for m, n in sorted(out.items(), reverse=True)]


# ---------------------------------------------------------------- render
def render(session: Session, item: SalesMailItem) -> tuple[str, str, list[Attachment]]:
    c = json.loads(item.content)
    v = build_view(session, c["month"], set(c["codes"]), c["view"], item.recipient_name)
    cfg = get_email(session)
    files = []
    if cfg.attach_excel:
        files.append(Attachment(f"{v['stem']}.xlsx", excel(v), XLSX))
    if cfg.attach_dashboard:
        files.append(Attachment(f"{v['stem']}_dashboard.html", dashboard(v), "text/html"))
    return _env.get_template("sales_monthly.html").render(v=v), text(v), files


def text(v: dict) -> str:
    lines = [f"Dear {v['recipient']},", "", f"Field sales attendance for {v['month_long']}: {v['work_days']} day{'s' if v['work_days'] != 1 else ''}, {v['n']} people.",
             f"Attendance {v['pct'] if v['pct'] is not None else '-'}% | Absent days {v['absent']} | Late days {v['late']} | "
             f"Days needing checking {v['flag_days']}", ""]
    if len(v["weeks"]) > 1:
        lines += ["Week by week:"] + [f"- {w['week']} ({w['range']}): {w['pct']}%, {w['absent']} absent, {w['late']} late" for w in v["weeks"]] + [""]
    if v["attention"]:
        lines += ["Needs a conversation:"] + [f"- {p['name']} ({p['code']}): {'; '.join(p['reasons'])}" for p in v["attention"][:15]] + [""]
    if v["perfect"]:
        lines += ["Full attendance: " + ", ".join(p["name"] for p in v["perfect"][:40]), ""]
    lines.append("Automated email from the APIS HR Portal (source: Bizom).")
    return "\n".join(lines)


def excel(v: dict) -> bytes:
    buf = io.BytesIO()
    wb = xlsxwriter.Workbook(buf, {"in_memory": True, "strings_to_formulas": False, "strings_to_urls": False})
    head = wb.add_format({"bold": True, "font_color": "#FFFFFF", "bg_color": "#14213D", "text_wrap": True, "border": 1, "valign": "vcenter"})
    cell = wb.add_format({"border": 1, "border_color": "#E6E8EF", "valign": "vcenter"})
    wrap = wb.add_format({"border": 1, "border_color": "#E6E8EF", "valign": "vcenter", "text_wrap": True})
    bold = wb.add_format({"border": 1, "border_color": "#E6E8EF", "bold": True, "font_color": "#14213D"})
    big = wb.add_format({"border": 1, "border_color": "#E6E8EF", "bold": True, "font_size": 13, "font_color": "#14213D"})
    flag = wb.add_format({"border": 1, "border_color": "#E6E8EF", "bg_color": "#FDECEC", "text_wrap": True, "valign": "vcenter"})
    note = wb.add_format({"italic": True, "font_color": "#5D6577"})
    day_fmt = {k: wb.add_format({"align": "center", "bold": True, "font_size": 9, "border": 1, "border_color": "#FFFFFF", "bg_color": col,
                                 "font_color": "#334155" if k == "WO" else "#FFFFFF"})
               for k, col in (("P", "#16a34a"), ("LT", "#d97706"), ("HD", "#f59e0b"), ("L", "#64748b"), ("WO", "#cbd5e1"), ("A", "#dc2626"))}
    blank = wb.add_format({"border": 1, "border_color": "#F1F5F9", "bg_color": "#F8FAFC"})

    ws = wb.add_worksheet("Summary")
    ws.set_column(0, 0, 34)
    ws.set_column(1, 4, 14)
    excel_banner(wb, ws, [34, 14, 14, 14], f"Field sales attendance - {v['label']} - {v['recipient']}")
    for i, (k, val) in enumerate([("People", v["n"]), ("Days uploaded", v["work_days"]), ("Attendance %", v["pct"] if v["pct"] is not None else "-"),
                                  ("Absent days", v["absent"]), ("Late days", v["late"]), ("Leave days", v["leave"]),
                                  ("Days needing checking", v["flag_days"]), ("People needing a conversation", len(v["attention"])),
                                  ("Full attendance", len(v["perfect"]))], start=3):
        ws.write(i, 0, k, bold)
        ws.write(i, 1, val, big)
    ws.write(13, 0, f"Needs a conversation = {ABSENT_DAYS}+ absent days, {LATE_DAYS}+ late days or a warning sign on {REPEAT_DAYS}+ days.", note)
    ws.write(14, 0, "Warning signs are for checking with the person, not proof of anything.", note)

    good = {k: wb.add_format({"border": 1, "border_color": "#E6E8EF", "bold": True, "font_color": c, "num_format": "0.0"})
            for k, c in (("g", "#15803D"), ("w", "#B45309"), ("b", "#B91C1C"))}
    pf = lambda x: cell if x is None else good["g" if x >= 90 else "w" if x >= 75 else "b"]  # noqa: E731
    if v.get("trend"):
        wd = wb.add_worksheet("Day by day")
        excel_banner(wb, wd, [12, 8, 14, 9, 9], f"Day by day - {v['label']}", "Attendance % on working days (Sundays / holidays left out)")
        for j, (h, w) in enumerate([("Date", 12), ("Day", 8), ("Attendance %", 14), ("Absent", 9), ("Late", 9)]):
            wd.write(3, j, h, head)
            wd.set_column(j, j, w)
        for i, t in enumerate(v["trend"], start=4):
            wd.write(i, 0, t["label"], cell)
            wd.write(i, 1, t["weekday"], cell)
            if t["pct"] is None:
                wd.write(i, 2, "off day", note)
            else:
                wd.write_number(i, 2, t["pct"], pf(t["pct"]))
            wd.write(i, 3, t["absent"], cell)
            wd.write(i, 4, t["late"], cell)
        last = 3 + len(v["trend"])
        ch = wb.add_chart({"type": "line"})
        ch.add_series({"name": "Attendance %", "categories": ["Day by day", 4, 0, last, 0], "values": ["Day by day", 4, 2, last, 2],
                       "line": {"color": "#14213D", "width": 2.25}, "marker": {"type": "circle", "size": 5, "fill": {"color": "#F5B800"}}})
        colc = wb.add_chart({"type": "column"})
        colc.add_series({"name": "Absent", "categories": ["Day by day", 4, 0, last, 0], "values": ["Day by day", 4, 3, last, 3],
                         "fill": {"color": "#FCA5A5"}, "y2_axis": True})
        ch.combine(colc)
        ch.set_title({"name": f"{v['label']}: attendance % and absent people", "name_font": {"size": 12}})
        ch.set_y_axis({"min": 40, "max": 100})
        ch.set_legend({"position": "bottom"})
        ch.set_size({"width": 760, "height": 340})
        wd.insert_chart(3, 6, ch)
        wd.freeze_panes(4, 1)
    sc = v.get("scorecards") or []
    if len(sc) > 1:
        ws2 = wb.add_worksheet("Team scorecard")
        cols = [("Team head", 26), ("People", 8), (v["label"], 11), (v["prev_label"], 11), ("Change (points)", 10), ("Late %", 8), ("Absent days", 9),
                ("Need a conversation", 11), ("Full attendance", 9)] + [(w, 6) for w in v["weekdays"]] + [("Lowest attendance", 46)]
        excel_banner(wb, ws2, [w for _, w in cols], f"Team heads - {v['label']}", f"Lowest attendance first; compared with {v['prev_label']}; weekday columns = attendance % that weekday")
        for j, (h, w) in enumerate(cols):
            ws2.write(3, j, h, head)
            ws2.set_column(j, j, w)
        neg = wb.add_format({"border": 1, "border_color": "#E6E8EF", "bold": True, "font_color": "#B91C1C", "num_format": "+0.0;-0.0;0"})
        pos = wb.add_format({"border": 1, "border_color": "#E6E8EF", "font_color": "#15803D", "num_format": "+0.0;-0.0;0"})
        for i, r in enumerate(sc, start=4):
            vals = [r["team_head"], r["people"], r["pct"], r["prev_pct"], r["change"], r["late_pct"], r["absent"], r["attention"], r["perfect"],
                    *r["heat"], "; ".join(r["lowest"])]
            for j, x in enumerate(vals):
                f = pf(x) if j in (2, 3) else (neg if isinstance(x, (int, float)) and x < 0 else pos) if j == 4 and x is not None else wrap if j == len(vals) - 1 else cell
                ws2.write(i, j, "" if x is None else x, f)
        ws2.conditional_format(4, 9, 3 + len(sc), 8 + len(v["weekdays"]), {"type": "3_color_scale", "min_color": "#F8696B", "mid_color": "#FFEB84",
                               "max_color": "#63BE7B", "min_type": "num", "min_value": 60, "mid_type": "num", "mid_value": 85, "max_type": "num", "max_value": 100})
        ws2.autofilter(3, 0, 3 + len(sc), len(cols) - 1)
        ws2.freeze_panes(4, 1)
        bar = wb.add_chart({"type": "bar"})
        bar.add_series({"name": v["label"], "categories": ["Team scorecard", 4, 0, 3 + len(sc), 0], "values": ["Team scorecard", 4, 2, 3 + len(sc), 2],
                        "fill": {"color": "#14213D"}, "data_labels": {"value": True, "num_format": "0.0"}})
        bar.add_series({"name": v["prev_label"], "categories": ["Team scorecard", 4, 0, 3 + len(sc), 0], "values": ["Team scorecard", 4, 3, 3 + len(sc), 3],
                        "fill": {"color": "#F5B800"}})
        bar.set_title({"name": f"Attendance by team head: {v['label']} vs {v['prev_label']}", "name_font": {"size": 12}})
        bar.set_x_axis({"min": 50, "max": 100})
        bar.set_legend({"position": "bottom"})
        bar.set_size({"width": 680, "height": max(280, 34 * len(sc) + 90)})
        ws2.insert_chart(6 + len(sc), 0, bar)

    if len(v["teams"]) > 1:
        wt = wb.add_worksheet("Teams")
        cols = [("HOD", "hod", 22), ("Team head", "team_head", 24), ("People", "people", 9), ("Attendance %", "pct", 12), ("Absent days", "absent", 11), ("Late days", "late", 10)]
        for j, (h, _, w) in enumerate(cols):
            wt.write(0, j, h, head)
            wt.set_column(j, j, w)
        for i, t in enumerate(v["teams"], start=1):
            for j, (_, k, _) in enumerate(cols):
                wt.write(i, j, "" if t[k] is None else t[k], cell)

    ww = wb.add_worksheet("Weeks")
    for j, (h, w) in enumerate([("Week", 10), ("Dates", 18), ("Attendance %", 12), ("Absent", 9), ("Late", 8), ("Needing checking", 12)]):
        ww.write(0, j, h, head)
        ww.set_column(j, j, w)
    for i, w in enumerate(v["weeks"], start=1):
        for j, k in enumerate(["week", "range", "pct", "absent", "late", "flagged"]):
            ww.write(i, j, "" if w[k] is None else w[k], cell)
    if v["weeks"]:
        ch = wb.add_chart({"type": "column"})
        ch.add_series({"name": "Attendance %", "categories": ["Weeks", 1, 1, len(v["weeks"]), 1], "values": ["Weeks", 1, 2, len(v["weeks"]), 2],
                       "fill": {"color": "#16A34A"}, "data_labels": {"value": True}})
        ch.set_y_axis({"min": 0, "max": 100})
        ch.set_legend({"none": True})
        ch.set_title({"name": "Attendance % by week", "name_font": {"size": 11}})
        ww.insert_chart(len(v["weeks"]) + 2, 0, ch)

    wa = wb.add_worksheet("Needs a conversation")
    for j, (h, w) in enumerate([("Code", 10), ("Name", 26), ("Team head", 22), ("Absent", 8), ("Late", 7), ("Attendance %", 11), ("Why", 60)]):
        wa.write(0, j, h, head)
        wa.set_column(j, j, w)
    for i, p in enumerate(v["attention"], start=1):
        for j, val in enumerate([p["code"], p["name"], p["team_head"], p["absent"], p["late"], p["pct"], "; ".join(p["reasons"])]):
            wa.write(i, j, "" if val is None else val, flag if j == 6 else cell)
    if not v["attention"]:
        wa.write(1, 0, "Nobody this month.", note)

    chk = [p for p in v["people"] if p.get("checks") and (p["checks"]["location_days"] or p["checks"]["selfie_days"] or p["checks"]["unusual_days"])]
    if chk:
        wk = wb.add_worksheet("Location & selfie checks")
        for j, (h, w) in enumerate([("Code", 10), ("Name", 26), ("Team head", 22), ("Days with location signs", 12), ("Days with selfie signs", 12),
                                    ("Unusual days", 10), ("Highest risk (0-100)", 11), ("Most frequent signs", 50)]):
            wk.write(0, j, h, head)
            wk.set_column(j, j, w)
        chk.sort(key=lambda p: (-p["checks"]["max_risk"], -p["checks"]["location_days"] - p["checks"]["selfie_days"]))
        for i, p in enumerate(chk, start=1):
            c = p["checks"]
            for j, val in enumerate([p["code"], p["name"], p["team_head"], c["location_days"], c["selfie_days"], c["unusual_days"],
                                     c["max_risk"], "; ".join(c["top"])]):
                wk.write(i, j, val, flag if j == 7 and c["reasons"] else cell)
        wk.write(len(chk) + 2, 0, "Map and selfies of each day: HR Portal > Field Sales > Needs checking.", note)
        wk.freeze_panes(1, 2)

    wp = wb.add_worksheet("People")
    cols = [("Code", "code", 10), ("Name", "name", 26), ("Role", "designation", 8), ("Team head", "team_head", 22), ("Days", "days", 6),
            ("Present", "present", 8), ("Late", "late", 6), ("Half day", "half_day", 8), ("Leave", "leave", 7), ("Week off", "week_off", 8),
            ("Absent", "absent", 7), ("Attendance %", "pct", 11), ("Last month %", "prev_pct", 10), ("Change (points)", "change", 10),
            ("Avg time in market", "avg_market", 11), ("Days needing checking", "flag_days", 10),
            ("Warning signs (days)", "warn", 50)]
    if v["view"] != "team":
        cols.insert(4, ("HOD", "hod", 18))
    for j, (h, _, w) in enumerate(cols):
        wp.write(0, j, h, head)
        wp.set_column(j, j, w)
    for i, p in enumerate(v["people"], start=1):
        for j, (_, k, _) in enumerate(cols):
            val = "; ".join(f"{w['label']} ({w['days']})" for w in p["warnings"]) if k == "warn" else p.get(k)
            wp.write(i, j, "" if val is None else val, wrap if k == "warn" else cell)
    wp.autofilter(0, 0, len(v["people"]), len(cols) - 1)
    wp.freeze_panes(1, 2)

    wc = wb.add_worksheet("Calendar")
    wc.write(0, 0, "Code", head)
    wc.write(0, 1, "Name", head)
    wc.set_column(0, 0, 10)
    wc.set_column(1, 1, 26)
    for j, d in enumerate(v["days"], start=2):
        wc.write(0, j, d[8:10], head)
        wc.set_column(j, j, 4.3)
    for i, p in enumerate(sorted(v["people"], key=lambda p: p["name"]), start=1):
        wc.write(i, 0, p["code"], cell)
        wc.write(i, 1, p["name"], cell)
        for j, d in enumerate(v["days"], start=2):
            code = p["cal"].get(d, "")
            wc.write(i, j, code, day_fmt.get(code.rstrip("!"), blank))
    wc.write(len(v["people"]) + 2, 1, "P present · LT late · HD half day · L leave · WO week off · A absent · ! = a warning sign that day", note)
    wc.freeze_panes(1, 2)
    wb.close()
    return buf.getvalue()


def dashboard(v: dict) -> bytes:
    data = {k: v[k] for k in ("people", "weeks", "teams", "days", "colors", "trend", "scorecards", "weekdays", "prev_label", "month_long")}
    js = json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
    return _env.get_template("sales_monthly_dashboard.html").render(v=v, logo=logo_data_uri(), data_json=js, favicon_fs=favicon_data_uri("fs")).encode("utf-8")
