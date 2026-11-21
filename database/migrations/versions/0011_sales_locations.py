"""Module 2 - location checks: locations, phone codes, calls, outlets, case reviews; geo flags + photo link on the day row.

Revision ID: 0011
Revises: 0010
Create Date: 2026-11-21
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None

UTC = sa.DateTime(timezone=True)
BIGID = sa.BigInteger().with_variant(sa.Integer(), "sqlite")
S = "daily"


def _alter_schema() -> str | None:          # SQLite: tables live in one file (no "daily." prefix for ALTER)
    return None if op.get_bind().dialect.name == "sqlite" else S


def upgrade() -> None:
    s = S
    with op.batch_alter_table("sales_employee_day", schema=_alter_schema()) as b:
        b.add_column(sa.Column("geo_flags", sa.String(300)))
        b.add_column(sa.Column("geo_evidence", sa.Text()))
        b.add_column(sa.Column("photo_url", sa.String(500)))
    op.create_table(
        "sales_location",
        sa.Column("id", BIGID, autoincrement=True, nullable=False),
        sa.Column("code", sa.String(30), nullable=False),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("kind", sa.String(4), nullable=False),
        sa.Column("lat", sa.Float(), nullable=False),
        sa.Column("lng", sa.Float(), nullable=False),
        sa.Column("time", sa.String(8)),
        sa.Column("source", sa.String(10), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code", "day", "kind", name="uq_sales_location"),
        schema=s,
    )
    op.create_index("ix_sales_location_day", "sales_location", ["day"], schema=s)
    op.create_table(
        "sales_device",
        sa.Column("id", BIGID, autoincrement=True, nullable=False),
        sa.Column("code", sa.String(30), nullable=False),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("device", sa.String(64), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code", "day", name="uq_sales_device"),
        schema=s,
    )
    op.create_index("ix_sales_device_day", "sales_device", ["day", "device"], schema=s)
    op.create_table(
        "sales_call",
        sa.Column("id", BIGID, autoincrement=True, nullable=False),
        sa.Column("upload_id", sa.Integer(), nullable=False),
        sa.Column("code", sa.String(30), nullable=False),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("call_id", sa.String(40)),
        sa.Column("start", sa.String(8)),
        sa.Column("end", sa.String(8)),
        sa.Column("duration_s", sa.Integer()),
        sa.Column("lat", sa.Float()),
        sa.Column("lng", sa.Float()),
        sa.Column("outlet_id", sa.String(40)),
        sa.Column("beat_id", sa.String(40)),
        sa.Column("distance_m", sa.Float()),
        sa.Column("productive", sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(["upload_id"], [f"{S}.sales_day_upload.upload_id"], name="fk_sales_call_upload_id_sales_day_upload"),
        sa.PrimaryKeyConstraint("id"),
        schema=s,
    )
    op.create_index("ix_sales_call_upload", "sales_call", ["upload_id"], schema=s)
    op.create_index("ix_sales_call_day_code", "sales_call", ["day", "code"], schema=s)
    op.create_table(
        "sales_outlet",
        sa.Column("outlet_id", sa.String(40), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("beat_id", sa.String(40)),
        sa.Column("beat_name", sa.String(200)),
        sa.Column("category", sa.String(100)),
        sa.Column("pincode", sa.String(10)),
        sa.Column("lat", sa.Float()),
        sa.Column("lng", sa.Float()),
        sa.Column("updated_at", UTC, nullable=False),
        sa.PrimaryKeyConstraint("outlet_id"),
        schema=s,
    )
    op.create_table(
        "sales_case",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("code", sa.String(30), nullable=False),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("status", sa.String(10), nullable=False),
        sa.Column("note", sa.String(1000)),
        sa.Column("reviewed_by", sa.String(100)),
        sa.Column("reviewed_at", UTC),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code", "day", name="uq_sales_case"),
        schema=s,
    )


def downgrade() -> None:
    s = S
    for t in ("sales_case", "sales_outlet", "sales_call", "sales_device", "sales_location"):
        op.drop_table(t, schema=s)
    with op.batch_alter_table("sales_employee_day", schema=_alter_schema()) as b:
        b.drop_column("photo_url")
        b.drop_column("geo_evidence")
        b.drop_column("geo_flags")
