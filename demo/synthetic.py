"""SYNTHETIC data in the real Pocket HRMS "AttendanceSummary" layout (invented people).

Layout learned from the first real sample: 4 preamble rows, header on row 5, two rows
per employee (in time, then out time), no status column.
"""

from __future__ import annotations

import io
import random
from datetime import date

from openpyxl import Workbook

FIRST = ["Aarti", "Bimal", "Charu", "Deepak", "Ekta", "Firoz", "Gauri", "Harsh", "Isha", "Jatin", "Kavya", "Lalit",
         "Meera", "Naveen", "Ojas", "Pooja", "Rahul", "Sneha", "Tarun", "Usha", "Varun", "Yamini"]


def _employees() -> list[tuple[str, str, str, str]]:
    out = []
    for i in range(14):
        out.append((f"HO9{i:03d}", f"{FIRST[i % len(FIRST)]} Synth", "Head Office", "General Shift"))
    for i in range(12):
        out.append((f"RK9{i:04d}", f"{FIRST[(i + 5) % len(FIRST)]} Synth", "Plant", "General Shift"))
    for i in range(16):
        shift = "General Shift" if i < 5 else "Shift Not Assigned"
        out.append((f"SL9{i:04d}", f"{FIRST[(i + 9) % len(FIRST)]} Synth", "Sales", shift))
    out.append(("test", "Test Account", "AONE", "Shift Not Assigned"))       # excluded by default rules
    out.append(("SL0DUMMY", "Dummy Synth", "Sales", "Shift Not Assigned"))
    return out


EMPLOYEES = _employees()


def build_summary_xlsx(day: date, seed: int | None = None) -> bytes:
    """One synthetic day in the FINAL Pocket HRMS layout (one row per employee, In Time / Out Time columns,
    Type = A / P / leave code, blank spacer rows). Deterministic per date unless `seed` is given."""
    rng = random.Random(seed if seed is not None else day.toordinal())
    wb = Workbook()
    ws = wb.active
    ws.title = "AttendanceSummary"
    ws.append(["Generated with Pocket HRMS"])
    ws.append(["Head Office : SYNTHETIC ADDRESS"])
    ws.append(["AttendanceSummary"])
    ws.append(["Run Date", f"{day:%d/%m/%Y} 13:08"])
    ws.append(["Code", "Name", "Category", "Department", "Designation", "Date", "Shift Name", "In Time", "Out Time", "Duration",
               "Type", "Day", "Remarks"])
    d = day.strftime("%d/%m/%Y")
    for code, name, cat, shift in EMPLOYEES:
        roll = rng.random()
        remark = ""
        if shift == "Shift Not Assigned" and cat == "Sales":
            in_t, out_t, typ, portion = ("Unswipe", "Unswipe", "A", "") if roll < 0.85 else \
                (f"10:{rng.randint(0, 59):02d}", f"19:{rng.randint(0, 40):02d}", "P", "")
        elif roll < 0.06:
            in_t, out_t, typ, portion = "", "", rng.choice(["PL", "SL", "CL"]), "Full Day"
        elif roll < 0.08:
            in_t, out_t, typ, portion = "", "", "LD", "Full Day"
        elif roll < 0.10:
            in_t, out_t, typ, portion, remark = "09:30", "18:00", "P", "", "work from home"
        elif roll < 0.16:
            in_t, out_t, typ, portion = "Unswipe", "Unswipe", "A", ""                      # absent
        elif roll < 0.20:
            in_t, out_t, typ, portion = f"09:{rng.randint(0, 50):02d}", "Invalid", "", ""   # missing punch
        else:
            h_in = rng.choice([9, 9, 9, 9, 10]) if cat != "Plant" else rng.choice([8, 9, 9])
            in_t = f"{h_in:02d}:{rng.randint(0, 59):02d}"
            out_t = f"{rng.choice([17, 18, 18, 19, 20]):02d}:{rng.randint(0, 59):02d}"
            typ, portion = "P", ""
        dur = ""
        if in_t[:1].isdigit() and out_t[:1].isdigit():
            mins = (int(out_t[:2]) * 60 + int(out_t[3:])) - (int(in_t[:2]) * 60 + int(in_t[3:]))
            dur = f"{mins // 60}:{mins % 60:02d}"
        ws.append([code, name + " ", cat, "", "", d, shift, in_t, out_t, dur, typ, portion, remark])
        ws.append([])                                                       # spacer row, as in the real export
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


# Synthetic hierarchy: HOD -> department -> team lead -> reporting manager (example.com addresses only).
HODS = {
    "Head Office": [("Accounts", "Kiran Synth", "kiran.hod@example.com"), ("Information Technology", "Kiran Synth", "kiran.hod@example.com"),
                    ("Human Resources", "Lata Synth", "lata.hod@example.com")],
    "Plant": [("Production", "Mohan Synth", "mohan.hod@example.com")],
    "Sales": [("General Trade", "Nisha Synth", "nisha.hod@example.com"), ("Modern Trade", "Nisha Synth", "nisha.hod@example.com")],
}


def build_master_xlsx() -> bytes:
    """SYNTHETIC employee master in the layout of HR's Employee Amendment file (blank row, header on row 2).
    The last Sales employee is left out on purpose, so the demo shows the 'not in employee master' highlight."""
    wb = Workbook()
    ws = wb.active
    ws.title = "Employees"
    ws.append([])
    ws.append(["", "EMPLOYEE CODE", "Employee Name", "Department", "DOJ", "HOD", "Email ID - HOD", "Sub split ID", "Reporting Manager"])
    real = [e for e in EMPLOYEES if e[0] not in ("test", "SL0DUMMY")][:-1]
    for i, (code, name, cat, _shift) in enumerate(real):
        dept, hod, hod_mail = HODS[cat][i % len(HODS[cat])]
        lead = "" if i % 4 == 0 else f"{dept.split()[0].lower()}.lead@example.com"
        ws.append([i + 1, code, name, dept, f"{2015 + i % 10}-0{1 + i % 9}-15", hod, hod_mail, lead, f"{FIRST[(i + 3) % len(FIRST)]} Lead Synth"])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def build_permission_xlsx(day: date, seed: int | None = None) -> bytes:
    """SYNTHETIC Pocket HRMS Permission Report for one day (same layout as the real export; no reasons)."""
    rng = random.Random((seed if seed is not None else day.toordinal()) + 11)
    wb = Workbook()
    ws = wb.active
    ws.title = "PermissionReportAdmin"
    ws.append(["APIS INDIA LTD (SYNTHETIC)"])
    ws.append(["Head Office : SYNTHETIC ADDRESS"])
    ws.append(["Permission Report Manager"])
    ws.append([])
    ws.append(["EmployeeCode", "EmployeeName", "AppliedDate", "PerDate", "PerHour", "PerToHour", "ApprovedDate", "Reason", "Status"])
    d = day.strftime("%d/%m/%Y")
    office = [e for e in EMPLOYEES if e[2] in ("Head Office", "Plant")]
    for code, name, _cat, _shift in rng.sample(office, 4):
        late = rng.random() < 0.5
        start, end = ("09:30", "11:30") if late else ("16:00", "18:00")
        status = rng.choice(["Approved", "Approved", "Pending"])
        ws.append([code, name, f"{d} 08:30 AM", d, start, end, d if status == "Approved" else "", "", status])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
