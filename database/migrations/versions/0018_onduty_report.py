"""Module 1: the Pocket HRMS On Duty Report as a third daily dataset (stored file per day + the on-duty note per person).

Revision ID: 0018
Revises: 0017
Create Date: 2026-11-23
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0018"
down_revision = "0017"
branch_labels = None
depends_on = None

DAY_COLS = (("onduty_filename", 255), ("onduty_path", 500), ("onduty_sha256", 64))


def _s() -> str | None:
    return None if op.get_bind().dialect.name == "sqlite" else "daily"


def upgrade() -> None:
    with op.batch_alter_table("day_upload", schema=_s()) as b:
        for col, n in DAY_COLS:
            b.add_column(sa.Column(col, sa.String(n)))
    with op.batch_alter_table("employee_day", schema=_s()) as b:
        b.add_column(sa.Column("on_duty", sa.String(200)))


def downgrade() -> None:
    with op.batch_alter_table("employee_day", schema=_s()) as b:
        b.drop_column("on_duty")
    with op.batch_alter_table("day_upload", schema=_s()) as b:
        for col, _ in reversed(DAY_COLS):
            b.drop_column(col)
