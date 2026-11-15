"""Bizom as a second attendance source: Bizom file on each day, source columns on each row.

Revision ID: 0004
Revises: 0003
Create Date: 2026-11-15
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def _schema() -> str | None:
    # SQLite flattens schemas via schema_translate_map, which plain ALTER statements don't honour.
    return None if op.get_bind().dialect.name == "sqlite" else "daily"


def upgrade() -> None:
    with op.batch_alter_table("day_upload", schema=_schema()) as b:
        b.alter_column("original_filename", existing_type=sa.String(255), nullable=True)
        b.alter_column("stored_path", existing_type=sa.String(500), nullable=True)
        b.alter_column("sha256", existing_type=sa.String(64), nullable=True)
        b.add_column(sa.Column("bizom_filename", sa.String(255)))
        b.add_column(sa.Column("bizom_path", sa.String(500)))
        b.add_column(sa.Column("bizom_sha256", sa.String(64)))
    with op.batch_alter_table("employee_day", schema=_schema()) as b:
        b.add_column(sa.Column("source", sa.String(12)))
        b.add_column(sa.Column("bizom_status", sa.String(10)))
        b.add_column(sa.Column("designation", sa.String(60)))
        b.add_column(sa.Column("hq", sa.String(100)))


def downgrade() -> None:
    with op.batch_alter_table("employee_day", schema=_schema()) as b:
        for name in ("hq", "designation", "bizom_status", "source"):
            b.drop_column(name)
    with op.batch_alter_table("day_upload", schema=_schema()) as b:
        for name in ("bizom_sha256", "bizom_path", "bizom_filename"):
            b.drop_column(name)
