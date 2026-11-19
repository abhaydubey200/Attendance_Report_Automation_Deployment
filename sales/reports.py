"""Field Sales reports over any date range: per person (days, statuses, attendance %, how often a warning sign came up),
per day (trend), one person day by day, and the email log. Repeated warning signs are what point to a real pattern."""

from __future__ import annotations

import io
from collections import Counter, defaultdict
from datetime import date, timedelta

import xlsxwriter
from sqlalchemy import select
from sqlalchemy.orm import Session

from daily.analysis import t12
from daily.branding import excel_banner
from database.models.sales import SalesDayUpload, SalesEmployee, SalesEmployeeDay, SalesMailItem
from sales.util import utc_iso
from sales.analysis import STATUS_LABEL, WARNINGS
from sales.bizom import norm_code
from sales.report import hm, manager_label

MAX_DAYS = 186
REPEAT_DAYS = 3            # a warning sign on this many days or more in the period = a pattern


class ReportError(ValueError):
    pass


def _rows(session: Session, start: date, end: date, code: str | None = None):
    if end < start:
        raise ReportError("'To' is before 'From'.")
    if (end - start).days + 1 > MAX_DAYS:
        raise ReportError(f"Choose at most {MAX_DAYS} days.")
    q = (select(SalesDayUpload.report_date, SalesEmployeeDay).join(SalesDayUpload, SalesDayUpload.upload_id == SalesEmployeeDay.upload_id)
         .where(SalesDayUpload.is_current.is_(True), SalesDayUpload.report_date >= start, SalesDayUpload.report_date <= end))
    if code:
        q = q.where(SalesEmployeeDay.code == norm_code(code))
    return session.execute(q.order_by(SalesDayUpload.report_date)).all()


def _pct(c: Counter) -> float | None:
    due = sum(c.values()) - c["WEEK_OFF"]
    return round(100 * (c["PRESENT"] + c["LATE"] + 0.5 * c["HALF_DAY"]) / due, 1) if due else None


def attendance_report(session: Session, start: date, end: date, q: str = "", hod: str = "", team: str = "") -> dict:
    rows = _rows(session, start, end)
    people: dict[str, dict] = {}
    by_day: dict[date, Counter] = defaultdict(Counter)
    flags_by_day: Counter = Counter()
    staff = {e.code: e for e in session.scalars(select(SalesEmployee))}
    ql = q.strip().lower()
    for d, r in rows:
        m = staff.get(r.code)
        team_head = (m.manager_name if m else None) or ""
        if hod and (r.hod_name or "") != hod:
            continue
        if team and team_head != team:
            continue
        if ql and ql not in r.name.lower() and ql not in r.code.lower():
            continue
        p = people.setdefault(r.code, {"code": r.code, "name": r.name, "designation": r.designation or "", "zone": r.zone or "",
                                       "team_head": team_head, "hod": r.hod_name or "", "status": Counter(), "flags": Counter(),
                                       "flag_days": 0, "market": [], "km": 0.0, "first_day": d, "last_day": d})
        p["status"][r.status] += 1
        p["last_day"] = d
        fl = [f for f in (r.flags or "").split(",") if f]
        p["flags"].update(fl)
        p["flag_days"] += bool(fl)
        if r.market_minutes is not None:
            p["market"].append(r.market_minutes)
        p["km"] += r.km or 0
        by_day[d][r.status] += 1
        flags_by_day[d] += bool(fl)
    out_people = []
    for p in people.values():
        c = p.pop("status")
        fl = p.pop("flags")
        mk = p.pop("market")
        out_people.append({**p, "first_day": p["first_day"].isoformat(), "last_day": p["last_day"].isoformat(), "days": sum(c.values()),
                           **{k.lower(): c[k] for k in STATUS_LABEL}, "attendance_pct": _pct(c),
                           "avg_market": hm(round(sum(mk) / len(mk))) if mk else "", "km": round(p["km"], 1),
                           "warnings": [{"code": k, "label": WARNINGS[k][0], "level": WARNINGS[k][1], "days": n} for k, n in fl.most_common() if k in WARNINGS],
                           "repeat": [WARNINGS[k][0] for k, n in fl.items() if n >= REPEAT_DAYS and k in WARNINGS]})
    out_people.sort(key=lambda p: (-len(p["repeat"]), -p["flag_days"], -(p["absent"]), p["name"]))
    total = Counter()
    for c in by_day.values():
        total.update(c)
    days = [{"date": d.isoformat(), "people": sum(c.values()), "attendance_pct": _pct(c), **{k.lower(): c[k] for k in STATUS_LABEL},
             "flagged": flags_by_day[d]} for d, c in sorted(by_day.items())]
    hods = sorted({r.hod_name for _, r in rows if r.hod_name})
    teams = sorted({(staff[r.code].manager_name if r.code in staff and staff[r.code].manager_name else "") for _, r in rows} - {""})
    return {"from": start.isoformat(), "to": end.isoformat(), "days_uploaded": len(days), "people": out_people, "days": days,
            "totals": {**{k.lower(): total[k] for k in STATUS_LABEL}, "attendance_pct": _pct(total),
                       "person_days": sum(total.values()), "flagged_days": sum(flags_by_day.values()),
                       "repeat_people": sum(1 for p in out_people if p["repeat"])},
            "filters": {"hods": hods, "teams": teams}, "repeat_days": REPEAT_DAYS}


def employee_report(session: Session, code: str, start: date, end: date) -> dict:
    rows = _rows(session, start, end, code)
    m = session.scalar(select(SalesEmployee).where(SalesEmployee.code == norm_code(code)))
    if not rows and m is None:
        raise LookupError(code)
    days = []
    c = Counter()
    for d, r in rows:
        c[r.status] += 1
        days.append({"date": d.isoformat(), "status": r.status, "status_label": STATUS_LABEL.get(r.status, r.status), "leave": r.leave_type or "",
                     "not_marked": r.status == "ABSENT" and not r.bizom_status, "att": t12(r.attendance_time) or "",
                     "first": t12(r.first_activity) or "", "last": t12(r.last_activity) or "", "market": hm(r.market_minutes),
                     "km": r.km, "eod": t12(r.eod_time) or "", "calls": r.calls, "productive": r.productive_calls,
                     "warnings": [WARNINGS[f][0] for f in (r.flags or "").split(",") if f in WARNINGS]})
    last = rows[-1][1] if rows else None
    return {"code": norm_code(code), "name": m.name if m else last.name, "designation": (m.designation if m else last.designation) or "",
            "team_head": (m.manager_name if m else "") or "", "team_head_email": (m.manager_email if m else "") or "",
            "hod": (m.hod_name if m else last.hod_name) or "", "status": m.status if m else "NOT ON STAFF LIST",
            "manager_in_bizom": manager_label(last.manager_name) if last else "", "from": start.isoformat(), "to": end.isoformat(),
            "summary": {**{k.lower(): c[k] for k in STATUS_LABEL}, "attendance_pct": _pct(c), "days": sum(c.values()),
                        "flagged_days": sum(1 for d in days if d["warnings"])}, "days": days}


def report_excel(rep: dict) -> bytes:
    buf = io.BytesIO()
    wb = xlsxwriter.Workbook(buf, {"in_memory": True, "strings_to_formulas": False})
    head = wb.add_format({"bold": True, "font_color": "#FFFFFF", "bg_color": "#14213D", "text_wrap": True, "border": 1, "valign": "vcenter"})
    cell = wb.add_format({"border": 1, "border_color": "#E6E8EF"})
    flag = wb.add_format({"border": 1, "border_color": "#E6E8EF", "bg_color": "#FDECEC", "text_wrap": True})
    ws = wb.add_worksheet("People")
    cols = [("Code", "code", 10), ("Name", "name", 26), ("Role", "designation", 9), ("Team head", "team_head", 22), ("HOD", "hod", 18),
            ("Days", "days", 6), ("Present", "present", 8), ("Late", "late", 6), ("Half day", "half_day", 8), ("Leave", "leave", 7),
            ("Week off", "week_off", 8), ("Absent", "absent", 7), ("Attendance %", "attendance_pct", 11), ("Avg time in market", "avg_market", 11),
            ("KM", "km", 8), ("Days needing checking", "flag_days", 10), ("Repeated warning signs", "repeat", 40), ("All warning signs (days)", "warn", 50)]
    excel_banner(wb, ws, [w for _, _, w in cols], f"Field sales attendance - {rep['from']} to {rep['to']}",
                 f"{rep['days_uploaded']} days uploaded · repeated = on {rep['repeat_days']}+ days")
    for j, (h, _, w) in enumerate(cols):
        ws.write(3, j, h, head)
        ws.set_column(j, j, w)
    for i, p in enumerate(rep["people"], start=4):
        for j, (_, k, _) in enumerate(cols):
            v = ("; ".join(p["repeat"]) if k == "repeat" else "; ".join(f"{w['label']} ({w['days']})" for w in p["warnings"]) if k == "warn"
                 else p.get(k))
            ws.write(i, j, "" if v is None else v, flag if k == "repeat" and p["repeat"] else cell)
    ws.autofilter(3, 0, 3 + len(rep["people"]), len(cols) - 1)
    ws.freeze_panes(4, 2)
    wd = wb.add_worksheet("By day")
    dcols = [("Date", "date", 12), ("People", "people", 8), ("Attendance %", "attendance_pct", 11), ("Present", "present", 8),
             ("Late", "late", 6), ("Half day", "half_day", 8), ("Leave", "leave", 7), ("Week off", "week_off", 8), ("Absent", "absent", 7),
             ("Needing checking", "flagged", 10)]
    for j, (h, _, w) in enumerate(dcols):
        wd.write(0, j, h, head)
        wd.set_column(j, j, w)
    for i, d in enumerate(rep["days"], start=1):
        for j, (_, k, _) in enumerate(dcols):
            wd.write(i, j, "" if d.get(k) is None else d[k], cell)
    wb.close()
    return buf.getvalue()


def email_log(session: Session, limit: int = 1000) -> list[dict]:
    out = []
    for i in session.scalars(select(SalesMailItem).where(SalesMailItem.sent_at.is_not(None)).order_by(SalesMailItem.sent_at.desc()).limit(limit)):
        out.append({"id": i.id, "report_date": i.report_date.isoformat(), "kind": "Month-end" if i.recipient_key.startswith("MONTHLY:") else "Daily",
                    "recipient": i.recipient_name, "role": i.role, "to": i.to_addrs or "", "subject": i.subject, "status": i.status,
                    "note": i.note, "sent_at": utc_iso(i.sent_at), "sent_by": i.approved_by})
    return out


def default_range(session: Session) -> tuple[date, date]:
    last = session.scalar(select(SalesDayUpload.report_date).where(SalesDayUpload.is_current.is_(True)).order_by(SalesDayUpload.report_date.desc()))
    end = last or date.today()
    return end - timedelta(days=29), end
