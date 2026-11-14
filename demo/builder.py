"""Builds a self-contained DEMO database from synthetic data (python main.py demo).

Everything here is invented test data -- column names, employees and statuses -- so the
whole workflow can be seen end to end before real sample files and HR rules exist.
It never touches the real development database: the demo uses storage/demo/.
"""

from __future__ import annotations

import csv
import io
import random
import shutil
from datetime import date, timedelta
from pathlib import Path

from sqlalchemy import select

from core.config import Settings
from core.paths import PROJECT_ROOT
from database.connection import create_db_engine, session_scope
from database.migrate import upgrade_to_head
from database.models.hr import DimEmployee, EmployeeSourceMapping
from database.repositories.security_repository import SecurityRepository
from data_engine.employee_mapper import resolve_mapping
from demo.synthetic import DAILY_ORDER, EMPLOYEES, MASTER_ORDER, SCHEMAS, SOURCE_OF, build_dataset_files, dmy
from ingestion.dataset_registry import load_dataset_registry
from ingestion.schema_service import save_schema
from ingestion.upload_manager import confirm_upload, inspect_upload
from orchestration.pipeline import start_run

DEMO_DIR = PROJECT_ROOT / "storage" / "demo"
DEMO_DB = DEMO_DIR / "apis_mis_demo.db"
DEMO_STORAGE = DEMO_DIR / "files"
ACTOR = "demo:builder"


def demo_env() -> dict[str, str]:
    return {"DB_PROFILE": "dev_sqlite", "DB_SQLITE_PATH": str(DEMO_DB), "APP_STORAGE_DIR": str(DEMO_STORAGE)}


def _hrms_for(day: date) -> bytes:
    """Deterministic day-to-day variation so trends have shape."""
    rng = random.Random(day.toordinal())
    rows = []
    for code, *_ in EMPLOYEES:
        if code in ("TEST-0003", "TEST-0005"):
            continue                       # covered by the leave file
        roll = rng.random()
        status = "Present" if roll < 0.72 else "Absent" if roll < 0.84 else "WFH" if roll < 0.94 else "Half Day"
        times = ("09:%02d" % rng.randint(0, 40), "18:%02d" % rng.randint(0, 30)) if status in ("Present", "Half Day") else ("", "")
        rows.append([code, dmy(day), status, *times])
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(["Emp Code", "Date", "Status", "In", "Out"])
    w.writerows(rows)
    return buf.getvalue().encode()


def build(settings: Settings, days: int = 10, end: date | None = None, log=print) -> Path:
    if DEMO_DIR.exists():
        for path in DEMO_DIR.rglob("*"):
            if path.is_file():
                path.chmod(0o666)            # raw archive files are read-only by design
        shutil.rmtree(DEMO_DIR)
    DEMO_DIR.mkdir(parents=True)
    engine = create_db_engine(settings)
    upgrade_to_head(engine)
    registry = load_dataset_registry(settings.config_dir)
    with session_scope(engine) as s:
        SecurityRepository(s).sync_roles_and_permissions(settings.security)
        for ds, schema in SCHEMAS.items():
            save_schema(s, ds, schema, ACTOR, "SYNTHETIC DEMO schema - replace with one defined from real files")

    end = end or date.today() - timedelta(days=1)
    start = end - timedelta(days=days - 1)
    for i in range(days):
        day = start + timedelta(days=i)
        files = build_dataset_files(day)
        files["HRMS_ATTENDANCE"] = ("hrms_attendance.csv", _hrms_for(day))
        order = (MASTER_ORDER if i == 0 else []) + DAILY_ORDER
        for ds in order:
            name, data = files[ds]
            with session_scope(engine) as s:
                res = inspect_upload(s, settings, registry, filename=f"{day:%Y%m%d}_{name}", data=data, dataset_id=ds,
                                     source_system=SOURCE_OF[ds], reporting_date=day, sheet=None, header_row=1, actor=ACTOR)
            with session_scope(engine) as s:
                confirm_upload(s, settings, registry, token=res["token"], actor=ACTOR, acknowledge_review=True, supersede=True)
        if i == 2:   # an HR reviewer verifies the Bizom identities part-way through
            with session_scope(engine) as s:
                for bz, code in (("BZ-01", "TEST-0001"), ("BZ-02", "TEST-0002"), ("BZ-03", "TEST-0003")):
                    m = s.scalar(select(EmployeeSourceMapping).where(EmployeeSourceMapping.source_employee_id == bz))
                    emp = s.scalar(select(DimEmployee).where(DimEmployee.employee_code == code))
                    resolve_mapping(s, m.mapping_id, emp.employee_key, "demo:hr-reviewer")
        res = start_run(engine, settings, day, ACTOR)
        log(f"  {day:%d-%b-%Y}: {res.run_ref} -> {res.state}")
    engine.dispose()
    return DEMO_DB
