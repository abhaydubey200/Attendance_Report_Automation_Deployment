"""Bulk history load for Field Sales: a folder of Bizom exports covering many days (training data for the models).

Drop every file in one folder (any names, sub-folders allowed): multi-day AttendanceReport files, daily Attendance reports,
Attendance & EOD reports and Call Variance reports. Files are recognised by their columns; several files of the same kind
for one day (e.g. Call Variance exported in parts) are joined. Each day is counted and checked like a normal upload but
NO emails are prepared for past days. Days are loaded oldest first, so each day learns from the days before it. At the end
the unusual-day model and the risk scores are rebuilt once, and the selfies are queued for checking.
"""

from __future__ import annotations

import csv
import io
from collections import defaultdict
from datetime import date
from pathlib import Path

from database.connection import session_scope
from sales import bizom, geo, ml, service

DAILY = (bizom.ATTENDANCE, bizom.EOD, bizom.CALLS)


def _rows_to_csv(rows: list[list[str]]) -> bytes:
    buf = io.StringIO()
    csv.writer(buf, quoting=csv.QUOTE_ALL).writerows(rows)
    return buf.getvalue().encode("utf-8")


def _split_by_day(rows: list[list[str]], kind: str) -> dict[date, list[list[str]]]:
    """A daily-kind export that covers several days is split into one block of rows per day (header kept)."""
    found = bizom._header(rows)
    at, _k, col = found
    name = {bizom.ATTENDANCE: "date", bizom.EOD: "for_date", bizom.CALLS: "call_start_date"}[kind]
    out: dict[date, list[list[str]]] = defaultdict(list)
    for r in rows[at + 1:]:
        d = bizom._date(r[col[name]]) if name in col and col[name] < len(r) else None
        if d:
            out[d].append(r)
    return {d: [rows[at]] + rs for d, rs in out.items()}


def scan(folder: Path) -> tuple[list[tuple[str, bytes]], dict[date, dict[str, list[list[str]]]], list[str]]:
    history, days, skipped = [], defaultdict(lambda: defaultdict(list)), []
    for p in sorted(folder.rglob("*")):
        if not p.is_file() or p.suffix.lower() not in (".csv", ".xlsx") or p.name.startswith("~$"):
            continue
        data = p.read_bytes()
        try:
            rows = bizom.read_rows(data, p.name)
            kind = bizom.kind_of(rows)
        except bizom.BizomError as exc:
            skipped.append(f"{p.name}: {exc}")
            continue
        if kind == bizom.HISTORY:
            history.append((p.name, data))
        elif kind in DAILY:
            for d, block in _split_by_day(rows, kind).items():
                have = days[d][kind]
                if not have:
                    have.extend(block)
                else:                                     # another part of the same day: add its rows, skip repeats
                    seen = {tuple(r) for r in have[1:]}
                    have.extend(r for r in block[1:] if tuple(r) not in seen)
        else:
            skipped.append(f"{p.name}: not a Bizom Attendance, EOD, Call Variance or AttendanceReport export")
    return history, days, skipped


def load(engine, folder: Path, actor: str, replace: bool = False, progress=print) -> dict:
    history, days, skipped = scan(folder)
    res = {"history_files": len(history), "days_found": len(days), "days_loaded": 0, "days_skipped": 0, "problems": skipped[:50]}
    for name, data in history:
        with session_scope(engine) as s:
            r = service.import_history(s, name, data)
            progress(f"  history {name}: {r['from']} to {r['to']}, {r['locations_added']} locations")
    for d in sorted(days):
        kinds = days[d]
        if bizom.ATTENDANCE not in kinds:
            res["days_skipped"] += 1
            res["problems"].append(f"{d}: no Attendance report - EOD / Call Variance alone cannot be loaded")
            continue
        files = [(f"{k.lower()}_{d}.csv", _rows_to_csv(rows)) for k, rows in kinds.items()]
        try:
            with session_scope(engine) as s:
                if service.current_upload(s, d) and not replace:
                    res["days_skipped"] += 1
                    continue
                service.process(s, files, actor, replace=replace, plan_mail=False, rescore=False)
            res["days_loaded"] += 1
            if res["days_loaded"] % 10 == 0:
                progress(f"  {res['days_loaded']} days loaded (up to {d})")
        except service.UploadError as exc:
            res["days_skipped"] += 1
            res["problems"].append(f"{d}: {exc}")
    with session_scope(engine) as s:
        from sales import staffcheck
        res["not_bizom_users"] = staffcheck.reconcile(s)   # people who turned out never to use Bizom: not absent on any day
        res["details_filled"] = staffcheck.fill_details(s)  # designation / zone of absent people from their last Bizom day
    with session_scope(engine) as s:
        for d in sorted(days):                            # second pass: every day checked with the full set of usual places
            if service.current_upload(s, d):
                geo.check_day(s, d)
        res["scores"] = ml.rescore(s)
        res["purge"] = geo.purge(s)
    return res

