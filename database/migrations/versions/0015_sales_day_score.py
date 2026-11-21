"""Module 2 - learned scores per person-day (unusual-day score, risk score, reasons).

Revision ID: 0015
Revises: 0014
Create Date: 2026-11-21
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None

BIGID = sa.BigInteger().with_variant(sa.Integer(), "sqlite")
S = "daily"


def upgrade() -> None:
    op.create_table(
        "sales_day_score",
        sa.Column("id", BIGID, autoincrement=True, nullable=False),
        sa.Column("code", sa.String(30), nullable=False),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("anomaly", sa.Float()),
        sa.Column("unusual", sa.Boolean(), nullable=False),
        sa.Column("risk", sa.Integer(), nullable=False),
        sa.Column("reasons", sa.Text()),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code", "day", name="uq_sales_day_score"),
        schema=S,
    )
    op.create_index("ix_sales_day_score_day", "sales_day_score", ["day"], schema=S)


def downgrade() -> None:
    op.drop_table("sales_day_score", schema=S)
