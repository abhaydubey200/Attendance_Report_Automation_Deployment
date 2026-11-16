"""Pocket HRMS Permission Report as the second daily dataset (replaces Bizom).

Revision ID: 0006
Revises: 0005
Create Date: 2026-11-16
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def _schema() -> str | None:
    return None if op.get_bind().dialect.name == "sqlite" else "daily"


def upgrade() -> None:
    with op.batch_alter_table("day_upload", schema=_schema()) as b:
        b.add_column(sa.Column("permission_filename", sa.String(255)))
        b.add_column(sa.Column("permission_path", sa.String(500)))
        b.add_column(sa.Column("permission_sha256", sa.String(64)))
    with op.batch_alter_table("employee_day", schema=_schema()) as b:
        b.add_column(sa.Column("permission", sa.String(80)))


def downgrade() -> None:
    with op.batch_alter_table("employee_day", schema=_schema()) as b:
        b.drop_column("permission")
    with op.batch_alter_table("day_upload", schema=_schema()) as b:
        for name in ("permission_sha256", "permission_path", "permission_filename"):
            b.drop_column(name)
