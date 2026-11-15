"""Daily attendance tool tables (schema `daily`).

Replaces the earlier PRD-scale schema (see git tag v0.5.0-full). Generated once from
the ORM models and frozen. Only CREATE statements.

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-14
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if op.get_bind().dialect.name == "mssql":
        op.execute("IF SCHEMA_ID(N'daily') IS NULL EXEC(N'CREATE SCHEMA [daily]')")
    op.create_table('app_setting',
        sa.Column('key', sa.String(length=50), nullable=False),
        sa.Column('value', sa.Text(), nullable=False),
        sa.Column('updated_by', sa.String(length=100), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('key', name=op.f('pk_app_setting')),
        schema='daily'
    )
    op.create_table('day_upload',
        sa.Column('upload_id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('report_date', sa.Date(), nullable=False),
        sa.Column('original_filename', sa.String(length=255), nullable=False),
        sa.Column('stored_path', sa.String(length=500), nullable=False),
        sa.Column('sha256', sa.String(length=64), nullable=False),
        sa.Column('is_current', sa.Boolean(), nullable=False),
        sa.Column('employees', sa.Integer(), nullable=False),
        sa.Column('insights', sa.Text(), nullable=False),
        sa.Column('rules', sa.Text(), nullable=False),
        sa.Column('uploaded_by', sa.String(length=100), nullable=False),
        sa.Column('uploaded_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('upload_id', name=op.f('pk_day_upload')),
        schema='daily'
    )
    op.create_index('ix_day_upload_date', 'day_upload', ['report_date'], unique=False, schema='daily')
    op.create_table('recipient',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('name', sa.String(length=200), nullable=False),
        sa.Column('email', sa.String(length=320), nullable=False),
        sa.Column('scope', sa.String(length=100), nullable=False),
        sa.Column('active', sa.Boolean(), nullable=False),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_recipient')),
        sa.UniqueConstraint('email', 'scope', name=op.f('uq_recipient_email_scope')),
        schema='daily'
    )
    op.create_table('email_log',
        sa.Column('id', sa.BigInteger().with_variant(sa.Integer(), 'sqlite'), autoincrement=True, nullable=False),
        sa.Column('upload_id', sa.Integer(), nullable=False),
        sa.Column('scope', sa.String(length=100), nullable=False),
        sa.Column('recipients', sa.String(length=2000), nullable=False),
        sa.Column('subject', sa.String(length=300), nullable=False),
        sa.Column('mode', sa.String(length=10), nullable=False),
        sa.Column('status', sa.String(length=20), nullable=False),
        sa.Column('error', sa.String(length=500), nullable=True),
        sa.Column('outbox_file', sa.String(length=500), nullable=True),
        sa.Column('sent_by', sa.String(length=100), nullable=False),
        sa.Column('sent_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['upload_id'], ['daily.day_upload.upload_id'], name=op.f('fk_email_log_upload_id_day_upload')),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_email_log')),
        schema='daily'
    )
    op.create_index('ix_email_log_upload', 'email_log', ['upload_id'], unique=False, schema='daily')
    op.create_table('employee_day',
        sa.Column('id', sa.BigInteger().with_variant(sa.Integer(), 'sqlite'), autoincrement=True, nullable=False),
        sa.Column('upload_id', sa.Integer(), nullable=False),
        sa.Column('employee_code', sa.String(length=50), nullable=False),
        sa.Column('employee_name', sa.String(length=200), nullable=True),
        sa.Column('category', sa.String(length=100), nullable=False),
        sa.Column('shift_name', sa.String(length=100), nullable=True),
        sa.Column('in_time', sa.String(length=8), nullable=True),
        sa.Column('out_time', sa.String(length=8), nullable=True),
        sa.Column('punches', sa.Integer(), nullable=False),
        sa.Column('work_minutes', sa.Integer(), nullable=True),
        sa.Column('leave_type', sa.String(length=20), nullable=True),
        sa.Column('day_portion', sa.String(length=30), nullable=True),
        sa.Column('status', sa.String(length=20), nullable=False),
        sa.Column('late_minutes', sa.Integer(), nullable=False),
        sa.Column('early_minutes', sa.Integer(), nullable=False),
        sa.Column('flags', sa.String(length=200), nullable=True),
        sa.ForeignKeyConstraint(['upload_id'], ['daily.day_upload.upload_id'], name=op.f('fk_employee_day_upload_id_day_upload')),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_employee_day')),
        schema='daily'
    )
    op.create_index('ix_employee_day_code', 'employee_day', ['employee_code'], unique=False, schema='daily')
    op.create_index('ix_employee_day_upload', 'employee_day', ['upload_id'], unique=False, schema='daily')


def downgrade() -> None:
    op.drop_index("ix_employee_day_code", table_name="employee_day", schema="daily")
    op.drop_index("ix_employee_day_upload", table_name="employee_day", schema="daily")
    op.drop_table("employee_day", schema="daily")
    op.drop_index("ix_email_log_upload", table_name="email_log", schema="daily")
    op.drop_table("email_log", schema="daily")
    op.drop_table("recipient", schema="daily")
    op.drop_index("ix_day_upload_date", table_name="day_upload", schema="daily")
    op.drop_table("day_upload", schema="daily")
    op.drop_table("app_setting", schema="daily")
