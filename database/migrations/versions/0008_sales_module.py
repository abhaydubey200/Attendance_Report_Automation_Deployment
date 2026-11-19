"""Module 2 - Field Sales attendance (Bizom): staff list, processed days, person-days and emails.

New tables only; no Module 1 table is changed.

Revision ID: 0008
Revises: 0007
Create Date: 2026-11-19
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None

UTC = sa.DateTime(timezone=True)
BIGID = sa.BigInteger().with_variant(sa.Integer(), "sqlite")
S = "daily"


def upgrade() -> None:
    op.create_table(
        "sales_employee",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("code", sa.String(30), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("designation", sa.String(60)),
        sa.Column("zone", sa.String(60)),
        sa.Column("hq", sa.String(100)),
        sa.Column("channel", sa.String(100)),
        sa.Column("manager_name", sa.String(200)),
        sa.Column("manager_email", sa.String(200)),
        sa.Column("asm_name", sa.String(200)),
        sa.Column("asm_email", sa.String(200)),
        sa.Column("zonal_name", sa.String(200)),
        sa.Column("zonal_email", sa.String(200)),
        sa.Column("hod_name", sa.String(200)),
        sa.Column("hod_email", sa.String(200)),
        sa.Column("date_of_joining", sa.Date()),
        sa.Column("status", sa.String(10), nullable=False),
        sa.Column("exit_date", sa.Date()),
        sa.Column("source", sa.String(100)),
        sa.Column("updated_by", sa.String(100)),
        sa.Column("updated_at", UTC, nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_sales_employee"),
        sa.UniqueConstraint("code", name="uq_sales_employee_code"),
        schema=S,
    )
    op.create_table(
        "sales_day_upload",
        sa.Column("upload_id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("report_date", sa.Date(), nullable=False),
        sa.Column("is_current", sa.Boolean(), nullable=False),
        sa.Column("attendance_file", sa.String(255)),
        sa.Column("eod_file", sa.String(255)),
        sa.Column("calls_file", sa.String(255)),
        sa.Column("sha256", sa.String(200)),
        sa.Column("people", sa.Integer(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("uploaded_by", sa.String(100), nullable=False),
        sa.Column("uploaded_at", UTC, nullable=False),
        sa.PrimaryKeyConstraint("upload_id", name="pk_sales_day_upload"),
        schema=S,
    )
    op.create_index("ix_sales_day_upload_date", "sales_day_upload", ["report_date", "is_current"], schema=S)
    op.create_table(
        "sales_employee_day",
        sa.Column("id", BIGID, autoincrement=True, nullable=False),
        sa.Column("upload_id", sa.Integer(), nullable=False),
        sa.Column("code", sa.String(30), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("designation", sa.String(60)),
        sa.Column("zone", sa.String(60)),
        sa.Column("manager_name", sa.String(200)),
        sa.Column("zonal_name", sa.String(200)),
        sa.Column("hod_name", sa.String(200)),
        sa.Column("in_master", sa.Boolean(), nullable=False),
        sa.Column("status", sa.String(12), nullable=False),
        sa.Column("bizom_status", sa.String(20)),
        sa.Column("leave_type", sa.String(40)),
        sa.Column("attendance_time", sa.String(8)),
        sa.Column("first_activity", sa.String(8)),
        sa.Column("last_activity", sa.String(8)),
        sa.Column("market_minutes", sa.Integer()),
        sa.Column("km", sa.Float()),
        sa.Column("eod_time", sa.String(8)),
        sa.Column("attendance_variance_m", sa.Float()),
        sa.Column("photo", sa.Boolean()),
        sa.Column("calls", sa.Integer()),
        sa.Column("productive_calls", sa.Integer()),
        sa.Column("short_calls", sa.Integer()),
        sa.Column("telephonic_calls", sa.Integer()),
        sa.Column("beat_jump_calls", sa.Integer()),
        sa.Column("far_calls", sa.Integer()),
        sa.Column("max_call_distance_m", sa.Float()),
        sa.Column("fast_moves", sa.Integer()),
        sa.Column("order_value", sa.Float()),
        sa.Column("flags", sa.String(300)),
        sa.ForeignKeyConstraint(["upload_id"], [f"{S}.sales_day_upload.upload_id"], name="fk_sales_employee_day_upload_id_sales_day_upload"),
        sa.PrimaryKeyConstraint("id", name="pk_sales_employee_day"),
        schema=S,
    )
    op.create_index("ix_sales_employee_day_upload", "sales_employee_day", ["upload_id"], schema=S)
    op.create_index("ix_sales_employee_day_code", "sales_employee_day", ["code"], schema=S)
    op.create_table(
        "sales_mail_item",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("upload_id", sa.Integer(), nullable=False),
        sa.Column("report_date", sa.Date(), nullable=False),
        sa.Column("recipient_key", sa.String(200), nullable=False),
        sa.Column("recipient_name", sa.String(200), nullable=False),
        sa.Column("role", sa.String(60), nullable=False),
        sa.Column("to_addrs", sa.String(1000)),
        sa.Column("cc_addrs", sa.String(1000)),
        sa.Column("subject", sa.String(300), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("counts", sa.Text()),
        sa.Column("status", sa.String(12), nullable=False),
        sa.Column("note", sa.String(500)),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("outbox_file", sa.String(500)),
        sa.Column("sent_at", UTC),
        sa.Column("approved_by", sa.String(100)),
        sa.Column("created_at", UTC, nullable=False),
        sa.ForeignKeyConstraint(["upload_id"], [f"{S}.sales_day_upload.upload_id"], name="fk_sales_mail_item_upload_id_sales_day_upload"),
        sa.PrimaryKeyConstraint("id", name="pk_sales_mail_item"),
        schema=S,
    )
    op.create_index("ix_sales_mail_item_date", "sales_mail_item", ["report_date"], schema=S)


def downgrade() -> None:
    op.drop_index("ix_sales_mail_item_date", table_name="sales_mail_item", schema=S)
    op.drop_table("sales_mail_item", schema=S)
    op.drop_index("ix_sales_employee_day_code", table_name="sales_employee_day", schema=S)
    op.drop_index("ix_sales_employee_day_upload", table_name="sales_employee_day", schema=S)
    op.drop_table("sales_employee_day", schema=S)
    op.drop_index("ix_sales_day_upload_date", table_name="sales_day_upload", schema=S)
    op.drop_table("sales_day_upload", schema=S)
    op.drop_table("sales_employee", schema=S)
