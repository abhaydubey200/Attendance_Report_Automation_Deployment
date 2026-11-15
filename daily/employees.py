"""Employee master: HOD -> Team -> Reporting manager -> Employee.

* Imported from HR's "Employee Amendment" Excel (add and update only; nobody is removed).
* HR can add, edit, mark as Left (with last working day) and restore employees.
* Every change is recorded in ``employee_change`` with old and new values.
* Attendance rows are matched to the master by employee code; each HOD then receives
  the report for their own people automatically (HOD email from the master).
"""

from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from daily.settings_store import valid_email
from database.models.daily import Employee, EmployeeChange
from ingestion.file_reader import ReadError, read_raw

ACTIVE, LEFT = "ACTIVE", "LEFT"
DIRECT = "Direct to HOD"
EDITABLE = ("name", "department", "date_of_joining", "hod_name", "hod_email", "team_lead_email", "reporting_manager")
_SPLIT = re.compile(r"[,;/\s]+")

# Header names in the HR Excel (matched case-insensitively, spaces/NBSP collapsed).
COLUMNS = {
    "code": ("employee code", "emp code", "code"),
    "name": ("employee name", "name"),
    "department": ("department",),
    "date_of_joining": ("doj", "date of joining"),
    "hod_name": ("hod", "hod name"),
    "hod_email": ("email id - hod", "hod email", "email id hod"),
    "team_lead_email": ("sub split id", "team lead email", "sub split"),
    "reporting_manager": ("reporting manager",),
}


class EmployeeError(ValueError):
    """Shown to the user as-is."""


def _clean(value) -> str:
    return re.sub(r"\s+", " ", str(value or "").replace("\xa0", " ")).strip()


def norm_code(code: str) -> str:
    return _clean(code).upper()


def team_of(team_lead_email: str | None) -> str:
    """Team = the part of the team lead's email before '@' (as in HR's dashboard)."""
    email = _clean(team_lead_email)
    return email.split("@")[0].strip().lower() if email and "@" in email else DIRECT


def emails_in(value: str | None) -> list[str]:
    return [e for e in _SPLIT.split(_clean(value)) if e and valid_email(e)]


def parse_date(value) -> date | None:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = _clean(value)
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d-%b-%Y", "%d %b %Y", "%m/%d/%Y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    raise EmployeeError(f"Unrecognised date '{text}' (use YYYY-MM-DD).")


NOT_GIVEN = {"NA", "N/A", "N.A.", "-", "--", "NIL", "NONE", "NULL", "0"}


def _given(value) -> str:
    text = _clean(value)
    return "" if text.upper() in NOT_GIVEN else text


def _canonical(name: str, known: dict[str, str], title: bool = True) -> str:
    """One spelling per name: 'AMIT ANAND' and 'Amit Anand' become the same HOD."""
    name = _given(name)
    if not name:
        return ""
    key = name.casefold()
    if key not in known:
        known[key] = name.title() if title and name.isupper() and len(name) > 4 else name
    elif known[key].isupper() and not name.isupper():
        known[key] = name
    return known[key]


def to_dict(e: Employee) -> dict:
    return {"id": e.id, "code": e.code, "name": e.name, "department": e.department or "",
            "date_of_joining": e.date_of_joining.isoformat() if e.date_of_joining else None,
            "hod_name": e.hod_name or "", "hod_email": e.hod_email or "", "team_lead_email": e.team_lead_email or "",
            "team": team_of(e.team_lead_email), "reporting_manager": e.reporting_manager or "", "status": e.status,
            "exit_date": e.exit_date.isoformat() if e.exit_date else None, "source": e.source,
            "updated_at": e.updated_at.isoformat() if e.updated_at else None, "updated_by": e.updated_by}


def _log(session: Session, code: str, action: str, changes: dict | None, actor: str) -> None:
    session.add(EmployeeChange(employee_code=code, action=action, actor=actor,
                               changes=json.dumps(changes, default=str) if changes else None))


# ---------------------------------------------------------------------------- reading HR's Excel
def read_master_file(filename: str, data: bytes) -> list[dict]:
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext not in ("xlsx", "csv"):
        raise EmployeeError("Upload the employee list as .xlsx or .csv.")
    try:
        raw, _ = read_raw(data, ext)
    except ReadError as exc:
        raise EmployeeError(str(exc)) from exc
    header_at, mapping = None, {}
    for i, row in enumerate(raw[:20]):
        cells = [_clean(c).lower() for c in row]
        found = {}
        for field_, names in COLUMNS.items():
            for j, c in enumerate(cells):
                if c in names and j not in found.values():
                    found[field_] = j
                    break
        if "code" in found and "name" in found:
            header_at, mapping = i, found
            break
    if header_at is None:
        raise EmployeeError("Could not find the header row (needs 'EMPLOYEE CODE' and 'Employee Name').")
    out = []
    for row in raw[header_at + 1:]:
        rec = {f: (row[j] if j < len(row) else "") for f, j in mapping.items()}
        if not _clean(rec.get("code")) and not _clean(rec.get("name")):
            continue
        out.append(rec)
    if not out:
        raise EmployeeError("The file has no employee rows.")
    return out


# ---------------------------------------------------------------------------- validation
def _known_spellings(session: Session) -> tuple[dict[str, str], dict[str, str]]:
    hods: dict[str, str] = {}
    depts: dict[str, str] = {}
    for h, d in session.execute(select(Employee.hod_name, Employee.department)):
        if h:
            hods.setdefault(h.casefold(), h)
        if d:
            depts.setdefault(d.casefold(), d)
    return hods, depts


def _validated(data: dict, hods: dict[str, str], depts: dict[str, str], partial: bool = False) -> dict:
    out: dict = {}
    for f in EDITABLE:
        if f not in data:
            continue
        v = data[f]
        if f == "date_of_joining":
            out[f] = parse_date(v)
        elif f == "hod_name":
            out[f] = _canonical(v, hods) or None
        elif f == "department":
            out[f] = _canonical(v, depts, title=False) or None
        elif f in ("hod_email", "team_lead_email"):
            text = _given(v).lower()
            if text and not emails_in(text):
                raise EmployeeError(f"Invalid email in {'HOD email' if f == 'hod_email' else 'team lead email'}: {text}")
            out[f] = text or None
        elif f == "name":
            out[f] = _clean(v) or None
        else:
            out[f] = _given(v) or None
    if not partial and not out.get("name"):
        raise EmployeeError("Employee name is required.")
    if "name" in out and not out["name"]:
        raise EmployeeError("Employee name cannot be empty.")
    return out


# ---------------------------------------------------------------------------- CRUD
def get(session: Session, code: str) -> Employee:
    e = session.scalar(select(Employee).where(Employee.code == norm_code(code)))
    if e is None:
        raise LookupError(f"No employee with code {norm_code(code)}.")
    return e


def list_all(session: Session) -> list[Employee]:
    return list(session.scalars(select(Employee).order_by(Employee.code)))


def create(session: Session, data: dict, actor: str) -> Employee:
    code = norm_code(data.get("code", ""))
    if not code:
        raise EmployeeError("Employee code is required.")
    if session.scalar(select(Employee.id).where(Employee.code == code)) is not None:
        raise EmployeeError(f"Employee {code} already exists.")
    hods, depts = _known_spellings(session)
    values = _validated(data, hods, depts)
    if values.get("hod_name") and not values.get("hod_email"):
        values["hod_email"] = hod_directory(session).get(values["hod_name"], [None])[0]
    e = Employee(code=code, status=ACTIVE, source="MANUAL", updated_by=actor, **values)
    session.add(e)
    _log(session, code, "CREATE", {k: [None, v] for k, v in values.items() if v is not None}, actor)
    session.flush()
    return e


def update(session: Session, code: str, data: dict, actor: str) -> Employee:
    e = get(session, code)
    hods, depts = _known_spellings(session)
    values = _validated(data, hods, depts, partial=True)
    if "hod_name" in values and values["hod_name"] != e.hod_name and "hod_email" not in data:
        values["hod_email"] = hod_directory(session).get(values["hod_name"] or "", [None])[0]
    changes = {k: [getattr(e, k), v] for k, v in values.items() if getattr(e, k) != v}
    for k, (_, v) in changes.items():
        setattr(e, k, v)
    if changes:
        e.updated_by = actor
        _log(session, e.code, "UPDATE", changes, actor)
    session.flush()
    return e


def mark_left(session: Session, code: str, exit_date: date, actor: str) -> Employee:
    """'Delete' = mark as Left. The employee drops out of lists and reports after the last working day."""
    e = get(session, code)
    old = (e.status, e.exit_date)
    e.status, e.exit_date, e.updated_by = LEFT, exit_date, actor
    _log(session, e.code, "LEFT", {"status": [old[0], LEFT], "exit_date": [old[1], exit_date]}, actor)
    session.flush()
    return e


def restore(session: Session, code: str, actor: str) -> Employee:
    e = get(session, code)
    if e.status == ACTIVE:
        return e
    old_exit = e.exit_date
    e.status, e.exit_date, e.updated_by = ACTIVE, None, actor
    _log(session, e.code, "RESTORE", {"status": [LEFT, ACTIVE], "exit_date": [old_exit, None]}, actor)
    session.flush()
    return e


def history(session: Session, code: str, limit: int = 100) -> list[dict]:
    rows = session.scalars(select(EmployeeChange).where(EmployeeChange.employee_code == norm_code(code))
                           .order_by(EmployeeChange.id.desc()).limit(limit))
    return [{"action": c.action, "changes": json.loads(c.changes) if c.changes else {}, "actor": c.actor,
             "at": c.occurred_at.isoformat()} for c in rows]


# ---------------------------------------------------------------------------- import (add + update only)
@dataclass
class ImportResult:
    rows: int = 0
    added: int = 0
    updated: int = 0
    unchanged: int = 0
    kept_left: int = 0
    not_in_file: int = 0
    problems: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {"rows": self.rows, "added": self.added, "updated": self.updated, "unchanged": self.unchanged,
                "kept_left": self.kept_left, "not_in_file": self.not_in_file, "problems": self.problems[:50],
                "problem_count": len(self.problems)}


def import_rows(session: Session, rows: list[dict], actor: str) -> ImportResult:
    """New codes are added, existing ones updated. Nobody is removed; employees marked Left stay Left."""
    res = ImportResult(rows=len(rows))
    hods, depts = _known_spellings(session)
    existing = {e.code: e for e in list_all(session)}
    seen: set[str] = set()
    for n, raw in enumerate(rows, start=1):
        code = norm_code(raw.get("code", ""))
        if not code:
            res.problems.append(f"Row {n}: no employee code - skipped.")
            continue
        if code in seen:
            res.problems.append(f"{code}: appears more than once - first row used.")
            continue
        seen.add(code)
        try:
            values = _validated({k: v for k, v in raw.items() if k != "code"}, hods, depts)
        except EmployeeError as exc:
            # Keep the row; drop only the bad value so one typo doesn't block the import.
            res.problems.append(f"{code}: {exc}")
            fixed = dict(raw)
            for f in ("hod_email", "team_lead_email", "date_of_joining"):
                try:
                    _validated({f: raw.get(f)}, hods, depts, partial=True)
                except EmployeeError:
                    fixed[f] = None
            try:
                values = _validated({k: v for k, v in fixed.items() if k != "code"}, hods, depts)
            except EmployeeError as exc2:
                res.problems.append(f"{code}: {exc2} - skipped.")
                continue
        e = existing.get(code)
        if e is None:
            e = Employee(code=code, status=ACTIVE, source="IMPORT", updated_by=actor, **values)
            session.add(e)
            existing[code] = e
            _log(session, code, "IMPORT_ADD", None, actor)
            res.added += 1
            continue
        changes = {k: [getattr(e, k), v] for k, v in values.items() if getattr(e, k) != v}
        if changes:
            for k, (_, v) in changes.items():
                setattr(e, k, v)
            e.updated_by = actor
            _log(session, code, "IMPORT_UPDATE", changes, actor)
            res.updated += 1
        else:
            res.unchanged += 1
        if e.status == LEFT:
            res.kept_left += 1
    res.not_in_file = sum(1 for c, e in existing.items() if c not in seen and e.status == ACTIVE)
    session.flush()
    return res


# ---------------------------------------------------------------------------- lookups for reports
def hod_directory(session: Session) -> dict[str, list[str]]:
    """HOD name -> email address(es), the most common value among their active employees."""
    seen: dict[str, Counter] = {}
    for name, email in session.execute(select(Employee.hod_name, Employee.hod_email).where(Employee.status == ACTIVE)):
        if name:
            seen.setdefault(name, Counter())[(email or "").lower()] += 1
    out: dict[str, list[str]] = {}
    for name, counter in seen.items():
        best = next((e for e, _ in counter.most_common() if emails_in(e)), "")
        out[name] = list(dict.fromkeys(emails_in(best)))
    return out


@dataclass(frozen=True)
class MasterInfo:
    name: str
    department: str | None
    hod: str | None
    team: str
    manager: str | None
    status: str
    exit_date: date | None


def master_lookup(session: Session) -> dict[str, MasterInfo]:
    return {e.code: MasterInfo(e.name, e.department, e.hod_name, team_of(e.team_lead_email), e.reporting_manager,
                               e.status, e.exit_date) for e in list_all(session)}


def summary(session: Session) -> dict:
    emps = list_all(session)
    active = [e for e in emps if e.status == ACTIVE]
    directory = hod_directory(session)
    return {"total": len(emps), "active": len(active), "left": len(emps) - len(active),
            "hods": [{"name": h, "emails": directory.get(h, []),
                      "employees": sum(1 for e in active if e.hod_name == h),
                      "departments": sorted({e.department for e in active if e.hod_name == h and e.department})}
                     for h in sorted(directory)],
            "departments": sorted({e.department for e in active if e.department}),
            "hods_without_email": sorted(h for h, m in directory.items() if not m)}
