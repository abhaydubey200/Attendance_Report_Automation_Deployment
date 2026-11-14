"""Builds a self-contained DEMO database from synthetic data (python main.py demo).

Since 14-Nov-2026 all data comes from Pocket HRMS via the AttendanceSummary export,
so the demo uploads one synthetic AttendanceSummary per day (real layout, invented
people). It never touches the real development database: the demo uses storage/demo/.
"""

from __future__ import annotations

import shutil
from datetime import date, timedelta
from pathlib import Path

from core.config import Settings
from core.paths import PROJECT_ROOT
from database.connection import create_db_engine, session_scope
from database.migrate import upgrade_to_head
from database.repositories.security_repository import SecurityRepository
from demo.synthetic import build_summary_xlsx
from ingestion.dataset_registry import load_dataset_registry
from ingestion.upload_manager import confirm_upload, inspect_upload
from orchestration.pipeline import start_run

DEMO_DIR = PROJECT_ROOT / "storage" / "demo"
DEMO_DB = DEMO_DIR / "apis_mis_demo.db"
DEMO_STORAGE = DEMO_DIR / "files"
ACTOR = "demo:builder"


def demo_env() -> dict[str, str]:
    return {"DB_PROFILE": "dev_sqlite", "DB_SQLITE_PATH": str(DEMO_DB), "APP_STORAGE_DIR": str(DEMO_STORAGE)}


def build(settings: Settings, days: int = 10, end: date | None = None, log=print) -> Path:
    from main import seed_schemas

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
        seed_schemas(s, settings)

    end = end or date.today() - timedelta(days=1)
    start = end - timedelta(days=days - 1)
    for i in range(days):
        day = start + timedelta(days=i)
        with session_scope(engine) as s:
            res = inspect_upload(s, settings, registry, filename=f"AttendanceSummary_{day:%Y%m%d}_SYNTHETIC.xlsx",
                                 data=build_summary_xlsx(day), dataset_id="HRMS_ATTENDANCE_SUMMARY",
                                 source_system="POCKET_HRMS", reporting_date=day, sheet=None, header_row=1, actor=ACTOR)
        with session_scope(engine) as s:
            confirm_upload(s, settings, registry, token=res["token"], actor=ACTOR, acknowledge_review=True, supersede=True)
        run = start_run(engine, settings, day, ACTOR)
        log(f"  {day:%d-%b-%Y}: {run.run_ref} -> {run.state}")
    engine.dispose()
    return DEMO_DB
