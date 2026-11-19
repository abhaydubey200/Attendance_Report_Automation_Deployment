"""Field sales staff list (HR): import (add and update only, never deletes), list, export, mark as left.

Column names are matched loosely so HR's own headings work (Emp Code / Emp Id / Employee Code, Reporting Manager Email ...).
"""

from __future__ import annotations

import io
import re
from collections import Counter
from datetime import date, datetime

import xlsxwriter
from sqlalchemy import select
from sqlalchemy.orm import Session

from database.models.sales import SalesEmployee
from sales.bizom import norm_code
from sales.config import valid_email


class StaffError(ValueError):
    """Shown to the user as-is."""


def _k(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", str(s or "").lower())


ALIASES: dict[str, tuple[str, ...]] = {
    "code": ("empcode", "employeecode", "empid", "employeeid", "code", "emp_code", "ecode"),
    "name": ("name", "employeename", "empname", "fullname"),
    "designation": ("designation", "empdesignation", "role", "rolename"),
    "zone": ("zone", "region"),
    "hq": ("hq", "headquarter", "headquarterhq", "hqname", "location"),
    "channel": ("channel", "department", "businessunit", "businessunits", "division"),
    "manager_name": ("reportingmanager", "reportingmanagername", "manager", "managername", "immediatemanager", "asetsm"),
    "manager_email": ("reportingmanageremail", "reportingmanagermail", "manageremail", "rmemail", "subsplitid", "teamleademail"),
    "asm_name": ("asmrsm", "asm", "rsm", "asmname", "rsmname", "areamanager"),
    "asm_email": ("asmrsmemail", "asmemail", "rsmemail", "areamanageremail"),
    "zonal_name": ("zonalhead", "zonalmanager", "regionalmanager", "regionalhead", "zonalheadname"),
    "zonal_email": ("zonalheademail", "zonalmanageremail", "regionalmanageremail", "zonalemail", "regionalheademail"),
    "hod_name": ("hod", "hodname", "headofdepartment"),
    "hod_email": ("hodemail", "hodmail", "hodmailid", "hodemailid", "emailidhod", "emailhod", "mailidhod"),
    "date_of_joining": ("dateofjoining", "doj", "joiningdate"),
    "status": ("status", "employeestatus", "userstatus"),
    "exit_date": ("exitdate", "dateofleaving", "lastworkingday", "dol", "leavingdate"),
}
FIELDS = list(ALIASES)


def _date(v: str) -> date | None:
    v = str(v or "").strip()[:10]
    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%d-%b-%Y", "%d.%m.%Y"):
        try:
            return datetime.strptime(v, fmt).date()
        except ValueError:
            continue
    return None


def _header(rows: list[list[str]]) -> tuple[int, dict[str, int]]:
    lookup = {a: f for f, al in ALIASES.items() for a in al}
    for i, row in enumerate(rows[:15]):
        cols: dict[str, int] = {}
        for j, c in enumerate(row):
            f = lookup.get(_k(c))
            if f and f not in cols:
                cols[f] = j
        if "code" in cols and "name" in cols:
            return i, cols
    raise StaffError("No header row with an employee code column (Emp Code / Emp Id) and a name column was found.")


def import_rows(session: Session, rows: list[list[str]], actor: str, source: str, codes: list[str] | None = None) -> dict:
    """Add new staff and update the given fields of existing ones. Blank cells never wipe a stored value.
    ``codes``: only employee codes matching one of these patterns are taken (field sales, e.g. ^SL); others are skipped."""
    at, cols = _header(rows)
    keep = [re.compile(p, re.IGNORECASE) for p in (codes or [])]
    existing = {e.code: e for e in session.scalars(select(SalesEmployee))}
    added = updated = unchanged = not_field_sales = 0
    problems: list[str] = []
    seen: set[str] = set()
    for n, r in enumerate(rows[at + 1:], start=at + 2):
        g = lambda f: str(r[cols[f]]).strip() if f in cols and cols[f] < len(r) and r[cols[f]] is not None else ""  # noqa: E731
        code = norm_code(g("code"))
        if not code:
            continue
        if keep and not any(k.search(code) for k in keep):
            not_field_sales += 1                       # e.g. HO / RK staff: Module 1's people
            continue
        if code in seen:
            problems.append(f"Row {n}: {code} appears more than once; the first row was used.")
            continue
        seen.add(code)
        values: dict = {}
        for f in FIELDS:
            if f == "code" or f not in cols:
                continue
            v = g(f)
            if not v:
                continue
            if f.endswith("_email"):
                v = v.lower()
                if not valid_email(v):
                    problems.append(f"Row {n} ({code}): '{v}' is not an email address - left empty.")
                    continue
            elif f in ("date_of_joining", "exit_date"):
                v = _date(v)
                if v is None:
                    continue
            elif f == "status":
                v = "LEFT" if v.lower() in ("left", "inactive", "resigned", "exit", "terminated") else "ACTIVE"
            values[f] = v
        if values.get("exit_date") and "status" not in values:
            values["status"] = "LEFT"
        emp = existing.get(code)
        if emp is None:
            if not values.get("name"):
                problems.append(f"Row {n} ({code}): no name - skipped.")
                continue
            emp = SalesEmployee(code=code, status=values.pop("status", "ACTIVE"), source=source, updated_by=actor, **values)
            session.add(emp)
            existing[code] = emp
            added += 1
        else:
            changed = {f: v for f, v in values.items() if getattr(emp, f) != v}
            for f, v in changed.items():
                setattr(emp, f, v)
            if changed:
                emp.updated_by, emp.source = actor, source
                updated += 1
            else:
                unchanged += 1
    session.flush()
    return {"added": added, "updated": updated, "unchanged": unchanged, "not_field_sales": not_field_sales, "problems": problems[:50],
            "problem_count": len(problems), "columns": sorted(cols)}


def to_dict(e: SalesEmployee) -> dict:
    return {f: (getattr(e, f).isoformat() if isinstance(getattr(e, f), date) else getattr(e, f)) for f in ["code"] + FIELDS}


def summary(session: Session) -> dict:
    staff = list(session.scalars(select(SalesEmployee).order_by(SalesEmployee.name)))
    active = [e for e in staff if e.status == "ACTIVE"]
    levels = {lvl: sum(1 for e in active if getattr(e, f"{lvl}_email")) for lvl in ("manager", "asm", "zonal", "hod")}
    return {"total": len(staff), "active": len(active), "left": len(staff) - len(active),
            "with_email": levels, "no_route": sum(1 for e in active if not any(getattr(e, f"{lvl}_email") for lvl in levels)),
            "hods": [{"name": k[0], "email": k[1], "people": v} for k, v in
                     Counter((e.hod_name or "", e.hod_email or "") for e in active).most_common()],
            "zonal": [{"name": k[0], "email": k[1], "people": v} for k, v in
                      Counter((e.zonal_name or "", e.zonal_email or "") for e in active).most_common()]}


def export_xlsx(session: Session) -> bytes:
    staff = list(session.scalars(select(SalesEmployee).order_by(SalesEmployee.code)))
    heads = ["Emp Code", "Name", "Designation", "Zone", "HQ", "Channel", "Reporting Manager", "Reporting Manager Email", "ASM/RSM",
             "ASM/RSM Email", "Zonal Head", "Zonal Head Email", "HOD", "HOD Email", "Date of Joining", "Status", "Exit Date"]
    buf = io.BytesIO()
    wb = xlsxwriter.Workbook(buf, {"in_memory": True, "strings_to_formulas": False})
    ws = wb.add_worksheet("Field Sales Staff")
    head = wb.add_format({"bold": True, "font_color": "#FFFFFF", "bg_color": "#14213D", "border": 1})
    for j, h in enumerate(heads):
        ws.write(0, j, h, head)
        ws.set_column(j, j, 18 if "Email" in h or h in ("Name", "Reporting Manager", "Zonal Head", "HOD", "ASM/RSM") else 12)
    for i, e in enumerate(staff, start=1):
        d = to_dict(e)
        for j, f in enumerate(["code"] + FIELDS):
            ws.write(i, j, d[f] or "")
    ws.autofilter(0, 0, len(staff), len(heads) - 1)
    ws.freeze_panes(1, 2)
    wb.close()
    return buf.getvalue()


def mark_left(session: Session, code: str, exit_date: date | None, actor: str) -> SalesEmployee:
    e = session.scalar(select(SalesEmployee).where(SalesEmployee.code == norm_code(code)))
    if e is None:
        raise LookupError(code)
    e.status, e.exit_date, e.updated_by = "LEFT", exit_date, actor
    session.flush()
    return e


def restore(session: Session, code: str, actor: str) -> SalesEmployee:
    e = session.scalar(select(SalesEmployee).where(SalesEmployee.code == norm_code(code)))
    if e is None:
        raise LookupError(code)
    e.status, e.exit_date, e.updated_by = "ACTIVE", None, actor
    session.flush()
    return e


EDITABLE = [f for f in FIELDS if f not in ("code", "status", "exit_date")]


def _clean_values(data: dict) -> dict:
    out = {}
    for f in EDITABLE:
        if f not in data:
            continue
        v = data[f]
        v = (str(v).strip() if v is not None else "") or None
        if v and f.endswith("_email"):
            v = v.lower()
            if not valid_email(v):
                raise StaffError(f"'{v}' is not an email address.")
        if v and f == "date_of_joining":
            d = _date(v)
            if d is None:
                raise StaffError("Date of joining: use YYYY-MM-DD.")
            v = d
        out[f] = v
    return out


def add(session: Session, data: dict, actor: str) -> SalesEmployee:
    code = norm_code(str(data.get("code") or ""))
    if not re.match(r"^[A-Z]{2}\d{3,}$", code):
        raise StaffError("Enter the employee code, e.g. SL04650.")
    if session.scalar(select(SalesEmployee).where(SalesEmployee.code == code)):
        raise StaffError(f"{code} is already on the staff list.")
    values = _clean_values(data)
    if not values.get("name"):
        raise StaffError("Enter the name.")
    e = SalesEmployee(code=code, status="ACTIVE", source="added in the app", updated_by=actor, **values)
    session.add(e)
    session.flush()
    return e


def update(session: Session, code: str, data: dict, actor: str) -> SalesEmployee:
    e = session.scalar(select(SalesEmployee).where(SalesEmployee.code == norm_code(code)))
    if e is None:
        raise LookupError(code)
    values = _clean_values(data)
    if "name" in values and not values["name"]:
        raise StaffError("The name cannot be empty.")
    for f, v in values.items():
        setattr(e, f, v)
    e.updated_by, e.source = actor, "edited in the app"
    session.flush()
    return e
