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
