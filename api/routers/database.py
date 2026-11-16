"""Database screen: a READ-ONLY view of every table in the application's database.

Only SELECT statements are run. Table and column names are checked against the live schema before use
(never interpolated from the request), and secret-looking columns (password / secret / token) are masked.
"""

from __future__ import annotations

import csv
import datetime as dt
import io
import json
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import Response
from sqlalchemy import Engine, MetaData, String, Table, cast, func, inspect, or_, select

from api.deps import get_engine, require
from security.permissions import Perm, Principal

router = APIRouter(tags=["database"])

LOGICAL_SCHEMAS = ("daily", "security", "audit")      # other databases keep the tables in these schemas
CELL_LIMIT = 2000                                     # characters per cell on screen (CSV has the full value)
CSV_LIMIT = 200_000
MASK = "•••••• (hidden)"

DESCRIPTIONS = {
    "employee": "Employee master: code, name, department, HOD and routing",
    "employee_change": "History of every change to the employee master",
    "day_upload": "Uploaded days (Pocket HRMS files) and their analysis",
    "employee_day": "Attendance of each employee on each uploaded day",
    "mail_item": "Daily / monthly emails: planned, approved, sent",
    "email_log": "Email delivery log (audit)",
    "mail_recipient": "Per-recipient on/off switches",
    "app_setting": "Saved settings (rules and email)",
    "job_run": "Scheduled job history (daily job, backup, monthly, cleanup)",
    "monthly_summary": "Month-end summaries and archives",
    "user_activity_log": "Who did what in the application",
    "app_user": "Application users",
    "app_role": "Access roles",
    "permission": "Access permissions",
    "role_permission": "Permissions of each role",
    "user_role": "Roles of each user",
    "user_department_access": "Department access per user",
    "alembic_version": "Database structure version",
}


def _secret(column: str) -> bool:
    name = column.lower()
    return any(word in name for word in ("password", "secret", "token"))


def _tables(engine: Engine) -> dict[str, str | None]:
    """{display name: schema} for every table, read from the live database."""
    insp = inspect(engine)
    if engine.dialect.name == "sqlite":
        return {name: None for name in insp.get_table_names()}
    out: dict[str, str | None] = {}
    available = set(insp.get_schema_names())
    for schema in LOGICAL_SCHEMAS:
        if schema in available:
            out.update({f"{schema}.{name}": schema for name in insp.get_table_names(schema=schema)})
    return out


def _table(engine: Engine, name: str) -> Table:
    tables = _tables(engine)
    if name not in tables:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such table.")
    schema = tables[name]
    return Table(name.split(".")[-1], MetaData(), autoload_with=engine, schema=schema)


def _value(column: str, value, limit: int | None = CELL_LIMIT):
    if value is None:
        return None
    if _secret(column):
        return MASK
    if isinstance(value, (dt.datetime, dt.date, dt.time)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (bytes, bytearray, memoryview)):
        return f"<{len(bytes(value))} bytes>"
    if isinstance(value, (bool, int, float)):
        return value
    text = value if isinstance(value, str) else json.dumps(value, default=str)
    return text if limit is None or len(text) <= limit else text[:limit] + " …"


def _query(table: Table, q: str | None, sort: str | None, direction: str):
    stmt = select(table)
    if q and q.strip():
        like = f"%{q.strip()}%"
        stmt = stmt.where(or_(*[cast(c, String).ilike(like) for c in table.columns if not _secret(c.name)]))
    names = [c.name for c in table.columns]
    if sort:
        if sort not in names:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Unknown column.")
        col = table.c[sort]
        stmt = stmt.order_by(col.desc() if direction == "desc" else col.asc())
    else:                                                   # newest first when there is a primary key
        pk = list(table.primary_key.columns)
        stmt = stmt.order_by(*[c.desc() for c in pk]) if pk else stmt
    return stmt


@router.get("/db/tables")
def tables(_: Principal = Depends(require(Perm.MANAGE_SETTINGS)), engine: Engine = Depends(get_engine)) -> dict:
    out = []
    with engine.connect() as conn:
        for name in sorted(_tables(engine)):
            t = _table(engine, name)
            rows = conn.execute(select(func.count()).select_from(t)).scalar_one()
            out.append({"name": name, "rows": rows, "columns": len(t.columns),
                        "description": DESCRIPTIONS.get(name.split(".")[-1], "")})
    return {"database": engine.dialect.name, "tables": out}


@router.get("/db/tables/{name}")
def rows(name: str, q: str | None = None, sort: str | None = None, direction: str = Query("asc", pattern="^(asc|desc)$"),
         limit: int = Query(50, ge=1, le=500), offset: int = Query(0, ge=0),
         _: Principal = Depends(require(Perm.MANAGE_SETTINGS)), engine: Engine = Depends(get_engine)) -> dict:
    t = _table(engine, name)
    stmt = _query(t, q, sort, direction)
    cols = [c.name for c in t.columns]
    with engine.connect() as conn:
        total = conn.execute(select(func.count()).select_from(stmt.order_by(None).subquery())).scalar_one()
        data = conn.execute(stmt.limit(limit).offset(offset)).all()
    return {"name": name, "description": DESCRIPTIONS.get(name.split(".")[-1], ""), "total": total, "offset": offset,
            "limit": limit, "columns": [{"name": c.name, "type": str(c.type), "primary_key": c.primary_key,
                                         "hidden": _secret(c.name)} for c in t.columns],
            "rows": [[_value(c, v) for c, v in zip(cols, r)] for r in data]}


@router.get("/db/tables/{name}/csv")
def rows_csv(name: str, q: str | None = None, sort: str | None = None, direction: str = Query("asc", pattern="^(asc|desc)$"),
             _: Principal = Depends(require(Perm.MANAGE_SETTINGS)), engine: Engine = Depends(get_engine)) -> Response:
    t = _table(engine, name)
    cols = [c.name for c in t.columns]
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(cols)
    with engine.connect() as conn:
        for r in conn.execute(_query(t, q, sort, direction).limit(CSV_LIMIT)):
            w.writerow(["" if v is None else _value(c, v, None) for c, v in zip(cols, r)])
    filename = f"{name.replace('.', '_')}_{dt.date.today():%Y-%m-%d}.csv"
    return Response("﻿" + buf.getvalue(), media_type="text/csv; charset=utf-8",      # BOM: Excel opens UTF-8 correctly
                    headers={"Content-Disposition": f'attachment; filename="{filename}"'})
