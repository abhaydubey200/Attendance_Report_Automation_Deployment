"""Module 2 - expense claims removed (2026-11-21): Field Sales is for attendance, fraud checks and the auto-mailer only.
Drops the claim lines table created in 0012 (sales_history_day stays: it is attendance).

Revision ID: 0014
Revises: 0013
Create Date: 2026-11-21
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None

UTC = sa.DateTime(timezone=True)
BIGID = sa.BigInteger().with_variant(sa.Integer(), "sqlite")
S = "daily"


def upgrade() -> None:
    op.drop_index("ix_sales_claim_day_code", table_name="sales_claim", schema=S)
    op.drop_table("sales_claim", schema=S)


def downgrade() -> None:
    op.create_table(
        "sales_claim",
        sa.Column("id", BIGID, autoincrement=True, nullable=False),
        sa.Column("detail_id", sa.String(40), nullable=False),
        sa.Column("claim_id", sa.String(40)),
        sa.Column("code", sa.String(30), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("designation", sa.String(60)),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("submit_date", sa.Date()),
        sa.Column("claim_type", sa.String(100), nullable=False),
        sa.Column("present_type", sa.String(60)),
        sa.Column("mode", sa.String(40)),
        sa.Column("from_place", sa.String(120)),
        sa.Column("to_place", sa.String(120)),
        sa.Column("amount", sa.Float(), nullable=False),
        sa.Column("approved_amount", sa.Float()),
        sa.Column("approval_status", sa.String(60)),
        sa.Column("approver", sa.String(120)),
        sa.Column("images", sa.Text()),
        sa.Column("calls", sa.Integer()),
        sa.Column("orders", sa.Integer()),
        sa.Column("sales_value", sa.Float()),
        sa.Column("market_minutes", sa.Integer()),
        sa.Column("flags", sa.String(300)),
        sa.Column("evidence", sa.Text()),
        sa.Column("imported_by", sa.String(100)),
        sa.Column("imported_at", UTC, nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("detail_id", name="uq_sales_claim_detail"),
        schema=S,
    )
    op.create_index("ix_sales_claim_day_code", "sales_claim", ["day", "code"], schema=S)
