"""Module 1 - employee.also_to: extra recipients (e.g. a second HOD) who also get this person in their daily team email.

Revision ID: 0010
Revises: 0009
Create Date: 2026-11-21
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def _schema() -> str | None:
    return None if op.get_bind().dialect.name == "sqlite" else "daily"


def upgrade() -> None:
    with op.batch_alter_table("employee", schema=_schema()) as b:
        b.add_column(sa.Column("also_to", sa.String(500)))


def downgrade() -> None:
    with op.batch_alter_table("employee", schema=_schema()) as b:
        b.drop_column("also_to")
