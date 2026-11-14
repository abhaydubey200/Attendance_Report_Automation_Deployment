"""Alembic environment. Uses the application's engine factory so the same profile,
schema mapping and credential handling apply to migrations."""

from __future__ import annotations

from alembic import context

from core.config import get_settings
from database.connection import create_db_engine
from database.models import Base

config = context.config
target_metadata = Base.metadata


def _run(connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        include_schemas=True,
        compare_type=True,
        render_as_batch=connection.dialect.name == "sqlite",
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    # Tests / main.py may hand us an existing connection.
    connection = config.attributes.get("connection")
    if connection is not None:
        _run(connection)
        return
    engine = create_db_engine(get_settings())
    with engine.connect() as conn:
        _run(conn)


if context.is_offline_mode():
    raise SystemExit("Offline SQL generation is not supported; run migrations against a database.")
run_migrations_online()
