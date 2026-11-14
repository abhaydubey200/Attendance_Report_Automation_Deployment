"""Phase 1: logical schemas, security tables, user activity audit log.

Revision ID: 0001
Revises:
Create Date: 2026-11-14
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

SCHEMAS = ("staging", "hr", "attendance", "audit", "security", "reporting")
UTC = sa.DateTime(timezone=True)
BIGID = sa.BigInteger().with_variant(sa.Integer, "sqlite")


def upgrade() -> None:
    if op.get_bind().dialect.name == "mssql":
        for schema in SCHEMAS:
            op.execute(f"IF SCHEMA_ID(N'{schema}') IS NULL EXEC(N'CREATE SCHEMA [{schema}]')")

    op.create_table(
        "app_user",
        sa.Column("user_id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("username", sa.String(100), nullable=False),
        sa.Column("display_name", sa.String(200), nullable=False),
        sa.Column("email", sa.String(320)),
        sa.Column("password_hash", sa.String(100)),
        sa.Column("auth_provider", sa.String(20), nullable=False),
        sa.Column("is_active", sa.Boolean, nullable=False),
        sa.Column("failed_login_count", sa.Integer, nullable=False),
        sa.Column("locked_until", UTC),
        sa.Column("last_login_at", UTC),
        sa.Column("created_at", UTC, nullable=False),
        sa.Column("updated_at", UTC, nullable=False),
        sa.Column("created_by", sa.String(100)),
        sa.PrimaryKeyConstraint("user_id", name="pk_app_user"),
        sa.UniqueConstraint("username", name="uq_app_user_username"),
        schema="security",
    )
    op.create_table(
        "app_role",
        sa.Column("role_id", sa.Integer, autoincrement=True),
        sa.Column("role_code", sa.String(50), nullable=False),
        sa.Column("description", sa.String(500)),
        sa.PrimaryKeyConstraint("role_id", name="pk_app_role"),
        sa.UniqueConstraint("role_code", name="uq_app_role_role_code"),
        schema="security",
    )
    op.create_table(
        "permission",
        sa.Column("permission_id", sa.Integer, autoincrement=True),
        sa.Column("permission_code", sa.String(100), nullable=False),
        sa.Column("description", sa.String(500)),
        sa.PrimaryKeyConstraint("permission_id", name="pk_permission"),
        sa.UniqueConstraint("permission_code", name="uq_permission_permission_code"),
        schema="security",
    )
    op.create_table(
        "user_role",
        sa.Column("user_id", sa.Integer, nullable=False),
        sa.Column("role_id", sa.Integer, nullable=False),
        sa.Column("granted_at", UTC, nullable=False),
        sa.Column("granted_by", sa.String(100)),
        sa.PrimaryKeyConstraint("user_id", "role_id", name="pk_user_role"),
        sa.ForeignKeyConstraint(["user_id"], ["security.app_user.user_id"], name="fk_user_role_user_id_app_user"),
        sa.ForeignKeyConstraint(["role_id"], ["security.app_role.role_id"], name="fk_user_role_role_id_app_role"),
        schema="security",
    )
    op.create_table(
        "role_permission",
        sa.Column("role_id", sa.Integer, nullable=False),
        sa.Column("permission_id", sa.Integer, nullable=False),
        sa.PrimaryKeyConstraint("role_id", "permission_id", name="pk_role_permission"),
        sa.ForeignKeyConstraint(["role_id"], ["security.app_role.role_id"], name="fk_role_permission_role_id_app_role"),
        sa.ForeignKeyConstraint(
            ["permission_id"], ["security.permission.permission_id"], name="fk_role_permission_permission_id_permission"
        ),
        schema="security",
    )
    op.create_table(
        "user_department_access",
        sa.Column("user_id", sa.Integer, nullable=False),
        sa.Column("department_code", sa.String(50), nullable=False),
        sa.Column("granted_at", UTC, nullable=False),
        sa.Column("granted_by", sa.String(100)),
        sa.PrimaryKeyConstraint("user_id", "department_code", name="pk_user_department_access"),
        sa.ForeignKeyConstraint(
            ["user_id"], ["security.app_user.user_id"], name="fk_user_department_access_user_id_app_user"
        ),
        schema="security",
    )
    op.create_table(
        "user_activity_log",
        sa.Column("activity_id", BIGID, autoincrement=True),
        sa.Column("occurred_at", UTC, nullable=False),
        sa.Column("user_id", sa.Integer),
        sa.Column("username", sa.String(100)),
        sa.Column("action", sa.String(50), nullable=False),
        sa.Column("outcome", sa.String(20), nullable=False),
        sa.Column("detail", sa.Text),
        sa.PrimaryKeyConstraint("activity_id", name="pk_user_activity_log"),
        schema="audit",
    )
    op.create_index("ix_user_activity_log_occurred_at", "user_activity_log", ["occurred_at"], schema="audit")
    op.create_index("ix_user_activity_log_user_id", "user_activity_log", ["user_id"], schema="audit")


def downgrade() -> None:
    # Development only. Production migrations must not be destructive (PRD 10.4).
    op.drop_index("ix_user_activity_log_user_id", table_name="user_activity_log", schema="audit")
    op.drop_index("ix_user_activity_log_occurred_at", table_name="user_activity_log", schema="audit")
    for table in ("user_activity_log",):
        op.drop_table(table, schema="audit")
    for table in ("user_department_access", "role_permission", "user_role", "permission", "app_role", "app_user"):
        op.drop_table(table, schema="security")
