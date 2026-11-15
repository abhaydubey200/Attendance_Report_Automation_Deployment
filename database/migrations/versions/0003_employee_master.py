"""Employee master (HR-maintained) and master fields on each attendance row.

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-15
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None

UTC = sa.DateTime(timezone=True)
BIGID = sa.BigInteger().with_variant(sa.Integer(), "sqlite")


def _day_schema() -> str | None:
    # SQLite flattens schemas via schema_translate_map, which plain ALTER statements don't honour.
    return None if op.get_bind().dialect.name == "sqlite" else "daily"


def upgrade() -> None:
    op.create_table(
        "employee",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("code", sa.String(50), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("department", sa.String(100)),
        sa.Column("date_of_joining", sa.Date()),
        sa.Column("hod_name", sa.String(200)),
        sa.Column("hod_email", sa.String(320)),
        sa.Column("team_lead_email", sa.String(320)),
        sa.Column("reporting_manager", sa.String(200)),
        sa.Column("status", sa.String(10), nullable=False),
        sa.Column("exit_date", sa.Date()),
        sa.Column("source", sa.String(10), nullable=False),
        sa.Column("created_at", UTC, nullable=False),
        sa.Column("updated_at", UTC, nullable=False),
        sa.Column("updated_by", sa.String(100)),
        sa.PrimaryKeyConstraint("id", name="pk_employee"),
        sa.UniqueConstraint("code", name="uq_employee_code"),
        schema="daily",
    )
    op.create_index("ix_employee_hod", "employee", ["hod_name"], schema="daily")
    op.create_table(
        "employee_change",
        sa.Column("id", BIGID, autoincrement=True, nullable=False),
        sa.Column("employee_code", sa.String(50), nullable=False),
        sa.Column("action", sa.String(20), nullable=False),
        sa.Column("changes", sa.Text()),
        sa.Column("actor", sa.String(100), nullable=False),
        sa.Column("occurred_at", UTC, nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_employee_change"),
        schema="daily",
    )
    op.create_index("ix_employee_change_code", "employee_change", ["employee_code"], schema="daily")
    for name, length in (("department", 100), ("hod_name", 200), ("team", 100), ("reporting_manager", 200)):
        op.add_column("employee_day", sa.Column(name, sa.String(length)), schema=_day_schema())


def downgrade() -> None:
    with op.batch_alter_table("employee_day", schema=_day_schema()) as b:
        for name in ("reporting_manager", "team", "hod_name", "department"):
            b.drop_column(name)
    op.drop_index("ix_employee_change_code", table_name="employee_change", schema="daily")
    op.drop_table("employee_change", schema="daily")
    op.drop_index("ix_employee_hod", table_name="employee", schema="daily")
    op.drop_table("employee", schema="daily")
