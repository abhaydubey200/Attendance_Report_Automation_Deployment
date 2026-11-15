"""Builds a self-contained DEMO database from synthetic data (python main.py demo).

Uploads 10 synthetic Attendance Summary days and adds example recipients, so the whole
flow (insights, Excel, dashboard, emails in test mode) can be seen. Uses storage/demo/
only; never touches the real database.
"""

from __future__ import annotations

import os
import shutil
import stat
from datetime import date, timedelta
from pathlib import Path

from core.config import Settings
from core.paths import PROJECT_ROOT
from daily import employees
from daily.service import upload_files_and_send
from daily.settings_store import replace_recipients
from database.connection import create_db_engine, session_scope
from database.migrate import upgrade_to_head
from database.repositories.security_repository import SecurityRepository
from demo.synthetic import build_bizom_csv, build_master_xlsx, build_summary_xlsx

DEMO_DIR = PROJECT_ROOT / "storage" / "demo"
DEMO_DB = DEMO_DIR / "apis_attendance_demo.db"
DEMO_STORAGE = DEMO_DIR / "files"
ACTOR = "demo"

EXAMPLE_RECIPIENTS = [  # example.com addresses: test mode only, never delivered. HODs come from the employee master.
    {"name": "HR Team (demo)", "email": "hr@example.com", "scope": "ALL"},
    {"name": "Director (demo)", "email": "director@example.com", "scope": "ALL"},
]


def demo_env() -> dict[str, str]:
    return {"DB_PROFILE": "dev_sqlite", "DB_SQLITE_PATH": str(DEMO_DB), "APP_STORAGE_DIR": str(DEMO_STORAGE)}


def _force_remove(func, path, _exc) -> None:
    """Older demo builds archived files read-only; clear the flag and retry."""
    os.chmod(path, stat.S_IWRITE)
    func(path)


def build(settings: Settings, days: int = 10, end: date | None = None, log=print) -> Path:
    if DEMO_DIR.exists():
        shutil.rmtree(DEMO_DIR, onexc=_force_remove)
    DEMO_DIR.mkdir(parents=True)
    engine = create_db_engine(settings)
    upgrade_to_head(engine)
    with session_scope(engine) as s:
        SecurityRepository(s).sync_roles_and_permissions(settings.security)
        replace_recipients(s, EXAMPLE_RECIPIENTS)
        imported = employees.import_rows(s, employees.read_master_file("employees.xlsx", build_master_xlsx()), ACTOR)
        log(f"  employee master: {imported.added} synthetic employees")
    end = end or date.today() - timedelta(days=1)
    for i in range(days):
        day = end - timedelta(days=days - 1 - i)
        with session_scope(engine) as s:
            up, outcomes, _ = upload_files_and_send(s, settings, [
                (f"AttendanceSummary_{day:%Y%m%d}_SYNTHETIC.xlsx", build_summary_xlsx(day)),
                (f"BizomAttendance_{day:%Y%m%d}_SYNTHETIC.csv", build_bizom_csv(day))], ACTOR)
            sent = sum(1 for o in outcomes or [] if o.status in ("SAVED", "SENT"))
            log(f"  {day:%d-%b-%Y}: {up.employees} employees, {sent} emails saved to the outbox (test mode)")
    engine.dispose()
    return DEMO_DB
