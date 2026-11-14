"""Programmatic migration entry point (used by main.py and tests)."""

from __future__ import annotations

from alembic import command
from alembic.config import Config
from sqlalchemy import Engine

from core.paths import PROJECT_ROOT


def _alembic_config() -> Config:
    cfg = Config(str(PROJECT_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(PROJECT_ROOT / "database" / "migrations"))
    return cfg


def upgrade_to_head(engine: Engine) -> None:
    cfg = _alembic_config()
    with engine.begin() as connection:
        cfg.attributes["connection"] = connection
        command.upgrade(cfg, "head")


def head_revision() -> str | None:
    from alembic.script import ScriptDirectory

    return ScriptDirectory.from_config(_alembic_config()).get_current_head()
