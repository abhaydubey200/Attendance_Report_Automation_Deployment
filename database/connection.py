"""Database connection abstraction (PRD 10.1).

* ``mssql``  -- primary target, via pyodbc. Credentials only from environment variables.
* ``sqlite`` -- temporary development database. The logical SQL Server schemas
  (security, audit, ...) are flattened via ``schema_translate_map``; table names are
  unique across schemas so nothing collides. Rejected in production by Settings.
"""

from __future__ import annotations

import logging
import os
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Iterator, Mapping

from sqlalchemy import Engine, create_engine, event, text
from sqlalchemy.engine import URL
from sqlalchemy.orm import Session, sessionmaker

from core.config import DatabaseProfile, Settings
from core.exceptions import DatabaseConfigurationError

log = logging.getLogger(__name__)

LOGICAL_SCHEMAS: tuple[str, ...] = ("staging", "hr", "attendance", "audit", "security", "reporting", "daily")


def _truthy(value: str | None) -> bool:
    return (value or "").strip().lower() in {"1", "yes", "true"}


def build_url(profile: DatabaseProfile, env: Mapping[str, str] | None = None) -> URL:
    env = os.environ if env is None else env

    if profile.backend == "sqlite":
        assert profile.path is not None
        return URL.create("sqlite+pysqlite", database=str(profile.path))

    host, database = env.get("DB_HOST"), env.get("DB_NAME")
    if not host or not database:
        raise DatabaseConfigurationError("mssql profile requires DB_HOST and DB_NAME environment variables")

    query: dict[str, str] = {
        "driver": profile.driver or "ODBC Driver 18 for SQL Server",
        "Encrypt": "yes" if profile.encrypt else "no",
        "TrustServerCertificate": "yes" if profile.trust_server_certificate else "no",
        "Connection Timeout": str(profile.connect_timeout_seconds),
        "APP": "APIS-Attendance-MIS",
    }
    username = password = None
    if _truthy(env.get("DB_TRUSTED_CONNECTION")):
        query["Trusted_Connection"] = "yes"
    else:
        username, password = env.get("DB_USER"), env.get("DB_PASSWORD")
        if not username or not password:
            raise DatabaseConfigurationError(
                "mssql profile requires DB_USER and DB_PASSWORD, or DB_TRUSTED_CONNECTION=yes"
            )
    port = int(env["DB_PORT"]) if env.get("DB_PORT") else profile.port
    return URL.create(
        "mssql+pyodbc", username=username, password=password, host=host, port=port, database=database, query=query
    )


def _enable_sqlite_foreign_keys(dbapi_conn, _record) -> None:
    """Every SQLite connection: foreign keys on, WAL journal (readers never block the writer), a busy timeout
    so the web app and the scheduled job wait for each other instead of failing, and NORMAL sync (safe with WAL)."""
    cur = dbapi_conn.cursor()
    cur.execute("PRAGMA foreign_keys=ON")
    cur.execute("PRAGMA busy_timeout=15000")
    cur.execute("PRAGMA journal_mode=WAL")
    cur.execute("PRAGMA synchronous=NORMAL")
    cur.close()


def create_db_engine(settings: Settings, env: Mapping[str, str] | None = None) -> Engine:
    profile = settings.database
    url = build_url(profile, env)

    if profile.backend == "sqlite":
        assert profile.path is not None
        profile.path.parent.mkdir(parents=True, exist_ok=True)
        engine = create_engine(url, future=True)
        event.listen(engine, "connect", _enable_sqlite_foreign_keys)
        engine = engine.execution_options(schema_translate_map={s: None for s in LOGICAL_SCHEMAS})
    else:
        engine = create_engine(
            url,
            pool_pre_ping=True,
            pool_size=profile.pool_size,
            max_overflow=profile.max_overflow,
            fast_executemany=True,
        )
    # Never log the URL with credentials.
    log.info("database engine created", extra={"db_profile": profile.name, "backend": profile.backend})
    return engine


_session_factories: dict[int, sessionmaker[Session]] = {}


def session_factory(engine: Engine) -> sessionmaker[Session]:
    key = id(engine)
    if key not in _session_factories:
        _session_factories[key] = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    return _session_factories[key]


@contextmanager
def session_scope(engine: Engine) -> Iterator[Session]:
    """Transactional unit of work: commit on success, roll back on any exception."""
    session = session_factory(engine)()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


@dataclass(frozen=True)
class DatabaseStatus:
    reachable: bool
    backend: str
    profile: str
    schema_revision: str | None
    detail: str


def check_database(engine: Engine, settings: Settings) -> DatabaseStatus:
    profile = settings.database
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
            revision = None
            try:
                revision = conn.execute(text("SELECT version_num FROM alembic_version")).scalar()
            except Exception:  # table absent until init-db has run
                conn.rollback()
        detail = "connected" if revision else "connected; migrations not applied (run: python main.py init-db)"
        return DatabaseStatus(True, profile.backend, profile.name, revision, detail)
    except Exception as exc:  # report class only, never connection strings
        return DatabaseStatus(False, profile.backend, profile.name, None, f"{type(exc).__name__}: connection failed")
