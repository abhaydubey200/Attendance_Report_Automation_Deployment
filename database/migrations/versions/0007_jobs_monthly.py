"""Job history (unattended daily / monthly / backup / cleanup runs) and month-end summaries.

Revision ID: 0007
Revises: 0006
Create Date: 2026-11-16
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None

UTC = sa.DateTime(timezone=True)
BIGID = sa.BigInteger().with_variant(sa.Integer(), "sqlite")


def upgrade() -> None:
    op.create_table(
        "job_run",
        sa.Column("id", BIGID, autoincrement=True, nullable=False),
        sa.Column("job", sa.String(20), nullable=False),
        sa.Column("target", sa.String(20)),
        sa.Column("trigger", sa.String(20), nullable=False),
        sa.Column("status", sa.String(10), nullable=False),
        sa.Column("summary", sa.Text()),
        sa.Column("error", sa.String(1000)),
        sa.Column("started_by", sa.String(100), nullable=False),
        sa.Column("started_at", UTC, nullable=False),
        sa.Column("finished_at", UTC),
        sa.PrimaryKeyConstraint("id", name="pk_job_run"),
        schema="daily",
    )
    op.create_index("ix_job_run_started", "job_run", ["started_at"], schema="daily")
    op.create_table(
        "monthly_summary",
        sa.Column("month", sa.String(7), nullable=False),
        sa.Column("days", sa.Integer(), nullable=False),
        sa.Column("employees", sa.Integer(), nullable=False),
        sa.Column("attendance_pct", sa.String(10)),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("archive_path", sa.String(500)),
        sa.Column("archive_sha256", sa.String(64)),
        sa.Column("status", sa.String(12), nullable=False),
        sa.Column("generated_by", sa.String(100), nullable=False),
        sa.Column("generated_at", UTC, nullable=False),
        sa.Column("cleaned_at", UTC),
        sa.PrimaryKeyConstraint("month", name="pk_monthly_summary"),
        schema="daily",
    )


def downgrade() -> None:
    op.drop_table("monthly_summary", schema="daily")
    op.drop_index("ix_job_run_started", table_name="job_run", schema="daily")
    op.drop_table("job_run", schema="daily")
