"""Module 2 - confirmed selfie matches (image-detail comparison of look-alike pairs).

Revision ID: 0016
Revises: 0015
Create Date: 2026-11-22
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None

UTC = sa.DateTime(timezone=True)
BIGID = sa.BigInteger().with_variant(sa.Integer(), "sqlite")
S = "daily"


def upgrade() -> None:
    op.create_table(
        "sales_photo_pair",
        sa.Column("id", BIGID, autoincrement=True, nullable=False),
        sa.Column("a_id", BIGID, nullable=False),
        sa.Column("b_id", BIGID, nullable=False),
        sa.Column("points", sa.Integer()),
        sa.Column("checked_at", UTC, nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("a_id", "b_id", name="uq_sales_photo_pair"),
        schema=S,
    )


def downgrade() -> None:
    op.drop_table("sales_photo_pair", schema=S)
