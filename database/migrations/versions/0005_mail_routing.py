"""Per-recipient mail routing: planned emails (approve / send / audit), recipient switches,
routing issue on employees. Replaces the old category/ALL recipient list.

Revision ID: 0005
Revises: 0004
Create Date: 2026-11-15
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None

UTC = sa.DateTime(timezone=True)
BIGID = sa.BigInteger().with_variant(sa.Integer(), "sqlite")


def _schema() -> str | None:
    return None if op.get_bind().dialect.name == "sqlite" else "daily"


def upgrade() -> None:
    with op.batch_alter_table("employee", schema=_schema()) as b:
        b.add_column(sa.Column("routing_issue", sa.String(200)))
    op.create_table(
        "mail_recipient",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("email", sa.String(320), nullable=False),
        sa.Column("name", sa.String(200)),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("effective_from", sa.Date()),
        sa.Column("effective_to", sa.Date()),
        sa.Column("updated_by", sa.String(100)),
        sa.PrimaryKeyConstraint("id", name="pk_mail_recipient"),
        sa.UniqueConstraint("email", name="uq_mail_recipient_email"),
        schema="daily",
    )
    op.create_table(
        "mail_item",
        sa.Column("id", BIGID, autoincrement=True, nullable=False),
        sa.Column("upload_id", sa.Integer(), nullable=False),
        sa.Column("report_date", sa.Date(), nullable=False),
        sa.Column("recipient_key", sa.String(320), nullable=False),
        sa.Column("recipient_name", sa.String(200), nullable=False),
        sa.Column("role", sa.String(30), nullable=False),
        sa.Column("to_addrs", sa.String(2000)),
        sa.Column("cc_addrs", sa.String(2000)),
        sa.Column("subject", sa.String(300), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("counts", sa.Text(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("note", sa.String(500)),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("outbox_file", sa.String(500)),
        sa.Column("created_at", UTC, nullable=False),
        sa.Column("approved_by", sa.String(100)),
        sa.Column("sent_at", UTC),
        sa.ForeignKeyConstraint(["upload_id"], ["daily.day_upload.upload_id"], name="fk_mail_item_upload_id_day_upload"),
        sa.PrimaryKeyConstraint("id", name="pk_mail_item"),
        schema="daily",
    )
    op.create_index("ix_mail_item_day", "mail_item", ["report_date", "recipient_key"], schema="daily")
    op.drop_table("recipient", schema="daily")


def downgrade() -> None:
    op.create_table(
        "recipient",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("email", sa.String(320), nullable=False),
        sa.Column("scope", sa.String(100), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_recipient"),
        sa.UniqueConstraint("email", "scope", name="uq_recipient_email_scope"),
        schema="daily",
    )
    op.drop_index("ix_mail_item_day", table_name="mail_item", schema="daily")
    op.drop_table("mail_item", schema="daily")
    op.drop_table("mail_recipient", schema="daily")
    with op.batch_alter_table("employee", schema=_schema()) as b:
        b.drop_column("routing_issue")
