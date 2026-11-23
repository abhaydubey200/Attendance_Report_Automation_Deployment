"""Field Sales: each person's holiday state (which page of HR's yearly holiday list applies) and who confirmed it.

Revision ID: 0019
Revises: 0018
Create Date: 2026-11-24
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0019"
down_revision = "0018"
branch_labels = None
depends_on = None


def _s() -> str | None:
    return None if op.get_bind().dialect.name == "sqlite" else "daily"


def upgrade() -> None:
    with op.batch_alter_table("sales_employee", schema=_s()) as b:
        b.add_column(sa.Column("holiday_state", sa.String(40)))
        b.add_column(sa.Column("holiday_state_by", sa.String(120)))


def downgrade() -> None:
    with op.batch_alter_table("sales_employee", schema=_s()) as b:
        b.drop_column("holiday_state_by")
        b.drop_column("holiday_state")
