"""Module 2 accuracy: HQ / EX-HQ work per day (Bizom Present_Type) and a reason on case reviews.

Revision ID: 0017
Revises: 0016
Create Date: 2026-11-22
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0017"
down_revision = "0016"
branch_labels = None
depends_on = None


def _s() -> str | None:
    return None if op.get_bind().dialect.name == "sqlite" else "daily"


def upgrade() -> None:
    for table, col in (("sales_employee_day", "present_type"), ("sales_history_day", "present_type"), ("sales_case", "reason")):
        with op.batch_alter_table(table, schema=_s()) as b:
            b.add_column(sa.Column(col, sa.String(40)))


def downgrade() -> None:
    for table, col in (("sales_employee_day", "present_type"), ("sales_history_day", "present_type"), ("sales_case", "reason")):
        with op.batch_alter_table(table, schema=_s()) as b:
            b.drop_column(col)
