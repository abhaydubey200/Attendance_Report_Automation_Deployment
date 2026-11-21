"""Module 2 - photo checks: selfie fingerprints (never the photo) and their warning signs.

Revision ID: 0013
Revises: 0012
Create Date: 2026-11-21
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None

UTC = sa.DateTime(timezone=True)
BIGID = sa.BigInteger().with_variant(sa.Integer(), "sqlite")
S = "daily"


def upgrade() -> None:
    op.create_table(
        "sales_photo",
        sa.Column("id", BIGID, autoincrement=True, nullable=False),
        sa.Column("url", sa.String(600), nullable=False),
        sa.Column("kind", sa.String(10), nullable=False),
        sa.Column("code", sa.String(30), nullable=False),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("att_time", sa.String(8)),
        sa.Column("status", sa.String(10), nullable=False),
        sa.Column("error", sa.String(200)),
        sa.Column("tries", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.String(64)),
        sa.Column("phash", sa.String(16)),
        sa.Column("width", sa.Integer()),
        sa.Column("height", sa.Integer()),
        sa.Column("size_kb", sa.Integer()),
        sa.Column("faces", sa.Integer()),
        sa.Column("brightness", sa.Float()),
        sa.Column("sharpness", sa.Float()),
        sa.Column("exif_time", sa.String(19)),
        sa.Column("flags", sa.String(300)),
        sa.Column("evidence", sa.Text()),
        sa.Column("fetched_at", UTC),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("url", name="uq_sales_photo_url"),
        schema=S,
    )
    op.create_index("ix_sales_photo_status", "sales_photo", ["status"], schema=S)
    op.create_index("ix_sales_photo_day_code", "sales_photo", ["day", "code"], schema=S)
    op.create_index("ix_sales_photo_sha", "sales_photo", ["sha256"], schema=S)


def downgrade() -> None:
    op.drop_table("sales_photo", schema=S)
