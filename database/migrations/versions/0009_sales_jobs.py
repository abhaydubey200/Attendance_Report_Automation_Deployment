"""Module 2 - Field Sales job history (daily inbox job, month-end). New table only.

Revision ID: 0009
Revises: 0008
Create Date: 2026-11-19
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None

UTC = sa.DateTime(timezone=True)


def upgrade() -> None:
    op.create_table(
        "sales_job_run",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("job", sa.String(20), nullable=False),
        sa.Column("target", sa.String(20)),
        sa.Column("trigger", sa.String(20), nullable=False),
        sa.Column("status", sa.String(10), nullable=False),
        sa.Column("summary", sa.Text()),
        sa.Column("error", sa.String(1000)),
        sa.Column("started_by", sa.String(100), nullable=False),
        sa.Column("started_at", UTC, nullable=False),
        sa.Column("finished_at", UTC),
        sa.PrimaryKeyConstraint("id", name="pk_sales_job_run"),
        schema="daily",
    )
    op.create_index("ix_sales_job_run_started", "sales_job_run", ["started_at"], schema="daily")


def downgrade() -> None:
    op.drop_index("ix_sales_job_run_started", table_name="sales_job_run", schema="daily")
    op.drop_table("sales_job_run", schema="daily")
