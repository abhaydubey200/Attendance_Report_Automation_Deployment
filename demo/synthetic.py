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
    """One synthetic day. Deterministic per date unless `seed` is given."""
    rng = random.Random(seed if seed is not None else day.toordinal())
    wb = Workbook()
    ws = wb.active
    ws.title = "AttendanceSummary"
    ws.append(["Generated with Pocket HRMS"])
    ws.append(["Head Office : SYNTHETIC ADDRESS"])
    ws.append(["AttendanceSummary"])
    ws.append(["Run Date", f"{day:%d/%m/%Y} 15:36"])
    ws.append(["Code", "Name", "Category", "Date", "Shift Name", "In-Out Time", "Type", "Day", "Remarks"])
    d = day.strftime("%d/%m/%Y")
    for code, name, cat, shift in EMPLOYEES:
        roll = rng.random()
        if shift == "Shift Not Assigned" and cat == "Sales":
            rows = [("", "", "")] * 2 if roll < 0.85 else [(f"10:{rng.randint(0, 59):02d}", "", ""), (f"19:{rng.randint(0, 40):02d}", "", "")]
        elif roll < 0.06:
            rows = [("", rng.choice(["PL", "SL", "CL"]), "Full Day")] * 2
        elif roll < 0.08:
            rows = [("", "LD", "Full Day")] * 2
        elif roll < 0.15:
            rows = [("", "", "")] * 2                                   # absent
        elif roll < 0.19:
            rows = [(f"09:{rng.randint(0, 50):02d}", "", ""), ("", "", "")]   # single punch
        else:
            h_in = rng.choice([9, 9, 9, 9, 10]) if cat != "Plant" else rng.choice([8, 9, 9])
            m_in = rng.randint(0, 59)
            h_out = rng.choice([17, 18, 18, 19, 20])
            rows = [(f"{h_in:02d}:{m_in:02d}", "", ""), (f"{h_out:02d}:{rng.randint(0, 59):02d}", "", "")]
        for t, typ, portion in rows:
            ws.append([code, name + " ", cat, d, shift, t, typ, portion, "synthetic remark" if typ else ""])
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


def build_bizom_csv(day: date, seed: int | None = None) -> bytes:
    """SYNTHETIC Bizom attendance report for one day (same columns as the real export; no IMEI values).
    Covers the Sales staff, two AP promoters, a vacant position and a test user."""
    rng = random.Random((seed if seed is not None else day.toordinal()) + 7)
    head = ["Zone", "SubzoneName", "Name", "User_Name", "User_Id", "Employee_Id", "Role_id", "DOJ", "HQ", "Designation",
            "User_Status", "Inactive_Date", "Imei", f"Date_{day:%d-%m-%Y}_Attendance_Status", "P", "SL", "PL", "Leave", "WO",
            "Total_Month_Days", "Presence%", "Total_Leave"]
    people = [(code, name, "SO") for code, name, cat, _ in EMPLOYEES if cat == "Sales" and code.startswith("SL9")]
    people += [("AP90001", "Promoter One Synth", "Promoter"), ("AP90002", "Promoter Two Synth", "Promoter")]
    lines = [",".join(head)]
    for i, (code, name, desig) in enumerate(people):
        roll = rng.random()
        status = "P" if roll < 0.78 else "A" if roll < 0.9 else "WO" if roll < 0.95 else rng.choice(["PL", "SL", "CL"])
        lines.append(",".join(["GTR01", "SYNTH ZONE", name.upper(), code, str(100 + i), code, "7", "2024-01-15", "Synth HQ", desig,
                               "Active", "", "", status, "1" if status == "P" else "0", "0", "", "0", "0", "30", "3.33", "0"]))
    lines.append(",".join(["GTR01", "SYNTH ZONE", "VACANT", "Vacant_TSM_Synth", "900", "", "4", "", "", "TSM", "Active", "", "", "A",
                           "", "", "", "", "", "30", "0", ""]))
    lines.append(",".join(["GTR01", "SYNTH ZONE", "TEST USER", "TestMT_Synth", "901", "TEST", "7", "", "", "SO", "Active", "", "", "P",
                           "1", "0", "", "0", "0", "30", "3.33", "0"]))
    return ("﻿" + "\n".join(lines) + "\n").encode("utf-8")
