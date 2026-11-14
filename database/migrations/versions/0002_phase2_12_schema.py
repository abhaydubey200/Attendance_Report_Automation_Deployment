"""Phases 2-12: staging, hr, attendance, reporting and audit tables.

Generated once from the ORM models and frozen here (later model changes need a new
migration). Non-destructive: only CREATE statements.

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
    op.create_table('processing_run',
        sa.Column('run_id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('run_ref', sa.String(length=40), nullable=False),
        sa.Column('reporting_date', sa.Date(), nullable=False),
        sa.Column('version_no', sa.Integer(), nullable=False),
        sa.Column('input_key', sa.String(length=64), nullable=False),
        sa.Column('inputs', sa.Text(), nullable=False),
        sa.Column('rule_version', sa.String(length=50), nullable=False),
        sa.Column('rules_approved', sa.Boolean(), nullable=False),
        sa.Column('state', sa.String(length=30), nullable=False),
        sa.Column('is_current', sa.Boolean(), nullable=False),
        sa.Column('ai_status', sa.String(length=20), nullable=True),
        sa.Column('stats', sa.Text(), nullable=True),
        sa.Column('error', sa.String(length=1000), nullable=True),
        sa.Column('started_by', sa.String(length=100), nullable=False),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('approved_by', sa.String(length=100), nullable=True),
        sa.Column('approved_at', sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint('run_id', name=op.f('pk_processing_run')),
        sa.UniqueConstraint('run_ref', name=op.f('uq_processing_run_run_ref')),
        schema='attendance'
    )
    op.create_index('ix_processing_run_date', 'processing_run', ['reporting_date'], unique=False, schema='attendance')
    op.create_table('ai_execution_log',
        sa.Column('id', sa.BigInteger().with_variant(sa.Integer(), 'sqlite'), autoincrement=True, nullable=False),
        sa.Column('feature', sa.String(length=30), nullable=False),
        sa.Column('run_id', sa.Integer(), nullable=True),
        sa.Column('username', sa.String(length=100), nullable=True),
        sa.Column('model', sa.String(length=100), nullable=True),
        sa.Column('prompt_version', sa.String(length=20), nullable=True),
        sa.Column('status', sa.String(length=20), nullable=False),
        sa.Column('duration_ms', sa.Integer(), nullable=True),
        sa.Column('detail', sa.Text(), nullable=True),
        sa.Column('occurred_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_ai_execution_log')),
        schema='audit'
    )
    op.create_table('email_delivery_log',
        sa.Column('id', sa.BigInteger().with_variant(sa.Integer(), 'sqlite'), autoincrement=True, nullable=False),
        sa.Column('report_id', sa.Integer(), nullable=False),
        sa.Column('recipient', sa.String(length=320), nullable=False),
        sa.Column('mode', sa.String(length=10), nullable=False),
        sa.Column('status', sa.String(length=20), nullable=False),
        sa.Column('attempts', sa.Integer(), nullable=False),
        sa.Column('error', sa.String(length=500), nullable=True),
        sa.Column('sent_at', sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_email_delivery_log')),
        sa.UniqueConstraint('report_id', 'recipient', name=op.f('uq_email_delivery_log_report_id_recipient')),
        schema='audit'
    )
    op.create_table('exception_resolution_log',
        sa.Column('id', sa.BigInteger().with_variant(sa.Integer(), 'sqlite'), autoincrement=True, nullable=False),
        sa.Column('exception_id', sa.Integer(), nullable=False),
        sa.Column('from_status', sa.String(length=20), nullable=False),
        sa.Column('to_status', sa.String(length=20), nullable=False),
        sa.Column('actor', sa.String(length=100), nullable=False),
        sa.Column('comment', sa.String(length=1000), nullable=True),
        sa.Column('occurred_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_exception_resolution_log')),
        schema='audit'
    )
    op.create_index('ix_exception_resolution_log_exc', 'exception_resolution_log', ['exception_id'], unique=False, schema='audit')
    op.create_table('processing_log',
        sa.Column('id', sa.BigInteger().with_variant(sa.Integer(), 'sqlite'), autoincrement=True, nullable=False),
        sa.Column('run_id', sa.Integer(), nullable=False),
        sa.Column('stage', sa.String(length=30), nullable=False),
        sa.Column('outcome', sa.String(length=20), nullable=False),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('duration_ms', sa.Integer(), nullable=True),
        sa.Column('record_count', sa.Integer(), nullable=True),
        sa.Column('message', sa.String(length=1000), nullable=True),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_processing_log')),
        schema='audit'
    )
    op.create_index('ix_processing_log_run', 'processing_log', ['run_id'], unique=False, schema='audit')
    op.create_table('dim_department',
        sa.Column('department_code', sa.String(length=50), nullable=False),
        sa.Column('department_name', sa.String(length=200), nullable=False),
        sa.Column('parent_department_code', sa.String(length=50), nullable=True),
        sa.Column('hod_employee_code', sa.String(length=50), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False),
        sa.Column('source_upload_id', sa.Integer(), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('department_code', name=op.f('pk_dim_department')),
        schema='hr'
    )
    op.create_table('dim_employee',
        sa.Column('employee_key', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('employee_code', sa.String(length=50), nullable=False),
        sa.Column('employee_name', sa.String(length=200), nullable=True),
        sa.Column('designation', sa.String(length=200), nullable=True),
        sa.Column('employment_type', sa.String(length=50), nullable=True),
        sa.Column('employment_status', sa.String(length=50), nullable=True),
        sa.Column('joining_date', sa.Date(), nullable=True),
        sa.Column('exit_date', sa.Date(), nullable=True),
        sa.Column('department_code', sa.String(length=50), nullable=True),
        sa.Column('location_code', sa.String(length=50), nullable=True),
        sa.Column('reporting_manager_code', sa.String(length=50), nullable=True),
        sa.Column('source_upload_id', sa.Integer(), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('employee_key', name=op.f('pk_dim_employee')),
        sa.UniqueConstraint('employee_code', name=op.f('uq_dim_employee_employee_code')),
        schema='hr'
    )
    op.create_table('holiday_calendar',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('holiday_date', sa.Date(), nullable=False),
        sa.Column('holiday_name', sa.String(length=200), nullable=False),
        sa.Column('location_code', sa.String(length=50), nullable=True),
        sa.Column('source_upload_id', sa.Integer(), nullable=True),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_holiday_calendar')),
        sa.UniqueConstraint('holiday_date', 'location_code', name=op.f('uq_holiday_calendar_holiday_date_location_code')),
        schema='hr'
    )
    op.create_table('reporting_hierarchy',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('employee_code', sa.String(length=50), nullable=False),
        sa.Column('manager_code', sa.String(length=50), nullable=True),
        sa.Column('effective_from', sa.Date(), nullable=False),
        sa.Column('effective_to', sa.Date(), nullable=True),
        sa.Column('source_upload_id', sa.Integer(), nullable=True),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_reporting_hierarchy')),
        schema='hr'
    )
    op.create_table('dataset_schema',
        sa.Column('schema_id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('dataset_id', sa.String(length=50), nullable=False),
        sa.Column('version', sa.Integer(), nullable=False),
        sa.Column('status', sa.String(length=20), nullable=False),
        sa.Column('definition', sa.Text(), nullable=False),
        sa.Column('notes', sa.String(length=500), nullable=True),
        sa.Column('created_by', sa.String(length=100), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('schema_id', name=op.f('pk_dataset_schema')),
        sa.UniqueConstraint('dataset_id', 'version', name=op.f('uq_dataset_schema_dataset_id_version')),
        schema='staging'
    )
    op.create_table('upload_registry',
        sa.Column('upload_id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('dataset_id', sa.String(length=50), nullable=False),
        sa.Column('source_system', sa.String(length=20), nullable=False),
        sa.Column('reporting_date', sa.Date(), nullable=False),
        sa.Column('original_filename', sa.String(length=255), nullable=False),
        sa.Column('stored_path', sa.String(length=500), nullable=False),
        sa.Column('sha256', sa.String(length=64), nullable=False),
        sa.Column('size_bytes', sa.Integer(), nullable=False),
        sa.Column('file_type', sa.String(length=10), nullable=False),
        sa.Column('sheet_name', sa.String(length=100), nullable=True),
        sa.Column('header_row', sa.Integer(), nullable=False),
        sa.Column('schema_version', sa.Integer(), nullable=True),
        sa.Column('status', sa.String(length=30), nullable=False),
        sa.Column('validation_status', sa.String(length=20), nullable=False),
        sa.Column('total_rows', sa.Integer(), nullable=False),
        sa.Column('valid_rows', sa.Integer(), nullable=False),
        sa.Column('invalid_rows', sa.Integer(), nullable=False),
        sa.Column('duplicate_rows', sa.Integer(), nullable=False),
        sa.Column('warning_count', sa.Integer(), nullable=False),
        sa.Column('standardized_rows', sa.Integer(), nullable=False),
        sa.Column('is_current', sa.Boolean(), nullable=False),
        sa.Column('reprocess_of', sa.Integer(), nullable=True),
        sa.Column('superseded_by', sa.Integer(), nullable=True),
        sa.Column('uploaded_by', sa.String(length=100), nullable=False),
        sa.Column('uploaded_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['reprocess_of'], ['staging.upload_registry.upload_id'], name=op.f('fk_upload_registry_reprocess_of_upload_registry')),
        sa.PrimaryKeyConstraint('upload_id', name=op.f('pk_upload_registry')),
        schema='staging'
    )
    op.create_index('ix_upload_registry_dataset_date', 'upload_registry', ['dataset_id', 'reporting_date'], unique=False, schema='staging')
    op.create_index('ix_upload_registry_sha256', 'upload_registry', ['sha256'], unique=False, schema='staging')
    op.create_table('attendance_exceptions',
        sa.Column('exception_id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('run_id', sa.Integer(), nullable=False),
        sa.Column('employee_key', sa.Integer(), nullable=True),
        sa.Column('source_employee_id', sa.String(length=100), nullable=True),
        sa.Column('department_code', sa.String(length=50), nullable=True),
        sa.Column('attendance_date', sa.Date(), nullable=False),
        sa.Column('category', sa.String(length=30), nullable=False),
        sa.Column('severity', sa.String(length=10), nullable=False),
        sa.Column('source_values', sa.Text(), nullable=False),
        sa.Column('status', sa.String(length=20), nullable=False),
        sa.Column('assigned_to', sa.String(length=100), nullable=True),
        sa.Column('resolution', sa.String(length=30), nullable=True),
        sa.Column('resolved_status', sa.String(length=30), nullable=True),
        sa.Column('resolution_comment', sa.String(length=1000), nullable=True),
        sa.Column('resolved_by', sa.String(length=100), nullable=True),
        sa.Column('resolved_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('detected_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['run_id'], ['attendance.processing_run.run_id'], name=op.f('fk_attendance_exceptions_run_id_processing_run')),
        sa.PrimaryKeyConstraint('exception_id', name=op.f('pk_attendance_exceptions')),
        schema='attendance'
    )
    op.create_index('ix_attendance_exceptions_status', 'attendance_exceptions', ['status'], unique=False, schema='attendance')
    op.create_table('attendance_punch',
        sa.Column('id', sa.BigInteger().with_variant(sa.Integer(), 'sqlite'), autoincrement=True, nullable=False),
        sa.Column('upload_id', sa.Integer(), nullable=False),
        sa.Column('source_system', sa.String(length=20), nullable=False),
        sa.Column('source_record_id', sa.String(length=50), nullable=True),
        sa.Column('source_employee_id', sa.String(length=100), nullable=False),
        sa.Column('punch_time', sa.DateTime(timezone=True), nullable=False),
        sa.Column('attendance_date', sa.Date(), nullable=False),
        sa.Column('direction', sa.String(length=10), nullable=False),
        sa.Column('device_or_location', sa.String(length=100), nullable=True),
        sa.ForeignKeyConstraint(['upload_id'], ['staging.upload_registry.upload_id'], name=op.f('fk_attendance_punch_upload_id_upload_registry')),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_attendance_punch')),
        schema='attendance'
    )
    op.create_index('ix_attendance_punch_date_emp', 'attendance_punch', ['attendance_date', 'source_employee_id'], unique=False, schema='attendance')
    op.create_table('attendance_reconciliation',
        sa.Column('id', sa.BigInteger().with_variant(sa.Integer(), 'sqlite'), autoincrement=True, nullable=False),
        sa.Column('run_id', sa.Integer(), nullable=False),
        sa.Column('employee_key', sa.Integer(), nullable=True),
        sa.Column('source_employee_id', sa.String(length=100), nullable=True),
        sa.Column('attendance_date', sa.Date(), nullable=False),
        sa.Column('category', sa.String(length=30), nullable=False),
        sa.Column('bizom_value', sa.String(length=100), nullable=True),
        sa.Column('hrms_value', sa.String(length=100), nullable=True),
        sa.Column('detail', sa.String(length=300), nullable=True),
        sa.ForeignKeyConstraint(['run_id'], ['attendance.processing_run.run_id'], name=op.f('fk_attendance_reconciliation_run_id_processing_run')),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_attendance_reconciliation')),
        schema='attendance'
    )
    op.create_index('ix_attendance_reconciliation_run', 'attendance_reconciliation', ['run_id'], unique=False, schema='attendance')
    op.create_table('fact_attendance_daily',
        sa.Column('id', sa.BigInteger().with_variant(sa.Integer(), 'sqlite'), autoincrement=True, nullable=False),
        sa.Column('run_id', sa.Integer(), nullable=False),
        sa.Column('employee_key', sa.Integer(), nullable=False),
        sa.Column('attendance_date', sa.Date(), nullable=False),
        sa.Column('department_code', sa.String(length=50), nullable=True),
        sa.Column('location_code', sa.String(length=50), nullable=True),
        sa.Column('final_status', sa.String(length=30), nullable=False),
        sa.Column('bizom_status', sa.String(length=30), nullable=True),
        sa.Column('hrms_status', sa.String(length=30), nullable=True),
        sa.Column('leave_status', sa.String(length=30), nullable=True),
        sa.Column('first_in', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_out', sa.DateTime(timezone=True), nullable=True),
        sa.Column('punch_count', sa.Integer(), nullable=False),
        sa.Column('record_status', sa.String(length=20), nullable=False),
        sa.Column('rule_version', sa.String(length=50), nullable=False),
        sa.Column('reason', sa.String(length=300), nullable=True),
        sa.ForeignKeyConstraint(['employee_key'], ['hr.dim_employee.employee_key'], name=op.f('fk_fact_attendance_daily_employee_key_dim_employee')),
        sa.ForeignKeyConstraint(['run_id'], ['attendance.processing_run.run_id'], name=op.f('fk_fact_attendance_daily_run_id_processing_run')),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_fact_attendance_daily')),
        sa.UniqueConstraint('run_id', 'employee_key', 'attendance_date', name=op.f('uq_fact_attendance_daily_run_id_employee_key_attendance_date')),
        schema='attendance'
    )
    op.create_index('ix_fact_attendance_daily_date_dept', 'fact_attendance_daily', ['attendance_date', 'department_code'], unique=False, schema='attendance')
    op.create_table('leave_record',
        sa.Column('id', sa.BigInteger().with_variant(sa.Integer(), 'sqlite'), autoincrement=True, nullable=False),
        sa.Column('upload_id', sa.Integer(), nullable=False),
        sa.Column('source_system', sa.String(length=20), nullable=False),
        sa.Column('source_record_id', sa.String(length=50), nullable=True),
        sa.Column('source_employee_id', sa.String(length=100), nullable=False),
        sa.Column('leave_date', sa.Date(), nullable=False),
        sa.Column('leave_type', sa.String(length=100), nullable=True),
        sa.Column('source_approval_status', sa.String(length=100), nullable=True),
        sa.Column('approval_status', sa.String(length=20), nullable=False),
        sa.Column('day_portion', sa.String(length=20), nullable=False),
        sa.ForeignKeyConstraint(['upload_id'], ['staging.upload_registry.upload_id'], name=op.f('fk_leave_record_upload_id_upload_registry')),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_leave_record')),
        schema='attendance'
    )
    op.create_index('ix_leave_record_date_emp', 'leave_record', ['leave_date', 'source_employee_id'], unique=False, schema='attendance')
    op.create_table('source_attendance',
        sa.Column('id', sa.BigInteger().with_variant(sa.Integer(), 'sqlite'), autoincrement=True, nullable=False),
        sa.Column('upload_id', sa.Integer(), nullable=False),
        sa.Column('source_system', sa.String(length=20), nullable=False),
        sa.Column('source_record_id', sa.String(length=50), nullable=True),
        sa.Column('source_employee_id', sa.String(length=100), nullable=False),
        sa.Column('source_employee_name', sa.String(length=200), nullable=True),
        sa.Column('attendance_date', sa.Date(), nullable=False),
        sa.Column('source_status', sa.String(length=100), nullable=True),
        sa.Column('mapped_status', sa.String(length=30), nullable=True),
        sa.Column('first_in', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_out', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['upload_id'], ['staging.upload_registry.upload_id'], name=op.f('fk_source_attendance_upload_id_upload_registry')),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_source_attendance')),
        schema='attendance'
    )
    op.create_index('ix_source_attendance_date_emp', 'source_attendance', ['attendance_date', 'source_employee_id'], unique=False, schema='attendance')
    op.create_table('employee_org_history',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('employee_key', sa.Integer(), nullable=False),
        sa.Column('department_code', sa.String(length=50), nullable=True),
        sa.Column('location_code', sa.String(length=50), nullable=True),
        sa.Column('effective_from', sa.Date(), nullable=False),
        sa.Column('effective_to', sa.Date(), nullable=True),
        sa.Column('source_upload_id', sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(['employee_key'], ['hr.dim_employee.employee_key'], name=op.f('fk_employee_org_history_employee_key_dim_employee')),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_employee_org_history')),
        schema='hr'
    )
    op.create_index('ix_employee_org_history_emp_from', 'employee_org_history', ['employee_key', 'effective_from'], unique=False, schema='hr')
    op.create_table('employee_source_mapping',
        sa.Column('mapping_id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('source_system', sa.String(length=20), nullable=False),
        sa.Column('source_employee_id', sa.String(length=100), nullable=False),
        sa.Column('source_employee_name', sa.String(length=200), nullable=True),
        sa.Column('employee_key', sa.Integer(), nullable=True),
        sa.Column('status', sa.String(length=20), nullable=False),
        sa.Column('method', sa.String(length=20), nullable=True),
        sa.Column('suggested_employee_key', sa.Integer(), nullable=True),
        sa.Column('confidence', sa.Float(), nullable=True),
        sa.Column('reviewed_by', sa.String(length=100), nullable=True),
        sa.Column('reviewed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['employee_key'], ['hr.dim_employee.employee_key'], name=op.f('fk_employee_source_mapping_employee_key_dim_employee')),
        sa.PrimaryKeyConstraint('mapping_id', name=op.f('pk_employee_source_mapping')),
        sa.UniqueConstraint('source_system', 'source_employee_id', name=op.f('uq_employee_source_mapping_source_system_source_employee_id')),
        schema='hr'
    )
    op.create_table('ai_summary',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('run_id', sa.Integer(), nullable=False),
        sa.Column('scope', sa.String(length=60), nullable=False),
        sa.Column('status', sa.String(length=20), nullable=False),
        sa.Column('summary', sa.Text(), nullable=True),
        sa.Column('context', sa.Text(), nullable=False),
        sa.Column('model', sa.String(length=100), nullable=True),
        sa.Column('prompt_version', sa.String(length=20), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['run_id'], ['attendance.processing_run.run_id'], name=op.f('fk_ai_summary_run_id_processing_run')),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_ai_summary')),
        schema='reporting'
    )
    op.create_index('ix_ai_summary_run', 'ai_summary', ['run_id'], unique=False, schema='reporting')
    op.create_table('report_registry',
        sa.Column('report_id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('run_id', sa.Integer(), nullable=False),
        sa.Column('report_type', sa.String(length=20), nullable=False),
        sa.Column('department_code', sa.String(length=50), nullable=True),
        sa.Column('file_format', sa.String(length=10), nullable=False),
        sa.Column('report_version', sa.Integer(), nullable=False),
        sa.Column('file_path', sa.String(length=500), nullable=False),
        sa.Column('sha256', sa.String(length=64), nullable=False),
        sa.Column('provisional', sa.Boolean(), nullable=False),
        sa.Column('status', sa.String(length=20), nullable=False),
        sa.Column('generated_by', sa.String(length=100), nullable=False),
        sa.Column('generated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['run_id'], ['attendance.processing_run.run_id'], name=op.f('fk_report_registry_run_id_processing_run')),
        sa.PrimaryKeyConstraint('report_id', name=op.f('pk_report_registry')),
        schema='reporting'
    )
    op.create_index('ix_report_registry_run', 'report_registry', ['run_id'], unique=False, schema='reporting')
    op.create_table('upload_row',
        sa.Column('upload_id', sa.Integer(), nullable=False),
        sa.Column('row_number', sa.Integer(), nullable=False),
        sa.Column('data', sa.Text(), nullable=False),
        sa.Column('is_valid', sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(['upload_id'], ['staging.upload_registry.upload_id'], name=op.f('fk_upload_row_upload_id_upload_registry')),
        sa.PrimaryKeyConstraint('upload_id', 'row_number', name=op.f('pk_upload_row')),
        schema='staging'
    )
    op.create_table('validation_issue',
        sa.Column('issue_id', sa.BigInteger().with_variant(sa.Integer(), 'sqlite'), autoincrement=True, nullable=False),
        sa.Column('upload_id', sa.Integer(), nullable=False),
        sa.Column('row_number', sa.Integer(), nullable=True),
        sa.Column('column_name', sa.String(length=200), nullable=True),
        sa.Column('code', sa.String(length=50), nullable=False),
        sa.Column('severity', sa.String(length=10), nullable=False),
        sa.Column('message', sa.String(length=500), nullable=False),
        sa.ForeignKeyConstraint(['upload_id'], ['staging.upload_registry.upload_id'], name=op.f('fk_validation_issue_upload_id_upload_registry')),
        sa.PrimaryKeyConstraint('issue_id', name=op.f('pk_validation_issue')),
        schema='staging'
    )
    op.create_index('ix_validation_issue_upload_id', 'validation_issue', ['upload_id'], unique=False, schema='staging')
    op.create_table('attendance_adjustments',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('exception_id', sa.Integer(), nullable=False),
        sa.Column('employee_key', sa.Integer(), nullable=False),
        sa.Column('attendance_date', sa.Date(), nullable=False),
        sa.Column('adjusted_status', sa.String(length=30), nullable=False),
        sa.Column('reason', sa.String(length=1000), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False),
        sa.Column('created_by', sa.String(length=100), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['exception_id'], ['attendance.attendance_exceptions.exception_id'], name=op.f('fk_attendance_adjustments_exception_id_attendance_exceptions')),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_attendance_adjustments')),
        schema='attendance'
    )
    op.create_index('ix_attendance_adjustments_emp_date', 'attendance_adjustments', ['employee_key', 'attendance_date'], unique=False, schema='attendance')
    op.create_table('report_approval',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('report_id', sa.Integer(), nullable=False),
        sa.Column('decision', sa.String(length=20), nullable=False),
        sa.Column('actor', sa.String(length=100), nullable=False),
        sa.Column('comment', sa.String(length=1000), nullable=True),
        sa.Column('decided_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['report_id'], ['reporting.report_registry.report_id'], name=op.f('fk_report_approval_report_id_report_registry')),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_report_approval')),
        schema='reporting'
    )


def downgrade() -> None:
    # Development only. Production migrations must not be destructive (PRD 10.4).
    op.drop_table("report_approval", schema="reporting")
    op.drop_index("ix_attendance_adjustments_emp_date", table_name="attendance_adjustments", schema="attendance")
    op.drop_table("attendance_adjustments", schema="attendance")
    op.drop_index("ix_validation_issue_upload_id", table_name="validation_issue", schema="staging")
    op.drop_table("validation_issue", schema="staging")
    op.drop_table("upload_row", schema="staging")
    op.drop_index("ix_report_registry_run", table_name="report_registry", schema="reporting")
    op.drop_table("report_registry", schema="reporting")
    op.drop_index("ix_ai_summary_run", table_name="ai_summary", schema="reporting")
    op.drop_table("ai_summary", schema="reporting")
    op.drop_table("employee_source_mapping", schema="hr")
    op.drop_index("ix_employee_org_history_emp_from", table_name="employee_org_history", schema="hr")
    op.drop_table("employee_org_history", schema="hr")
    op.drop_index("ix_source_attendance_date_emp", table_name="source_attendance", schema="attendance")
    op.drop_table("source_attendance", schema="attendance")
    op.drop_index("ix_leave_record_date_emp", table_name="leave_record", schema="attendance")
    op.drop_table("leave_record", schema="attendance")
    op.drop_index("ix_fact_attendance_daily_date_dept", table_name="fact_attendance_daily", schema="attendance")
    op.drop_table("fact_attendance_daily", schema="attendance")
    op.drop_index("ix_attendance_reconciliation_run", table_name="attendance_reconciliation", schema="attendance")
    op.drop_table("attendance_reconciliation", schema="attendance")
    op.drop_index("ix_attendance_punch_date_emp", table_name="attendance_punch", schema="attendance")
    op.drop_table("attendance_punch", schema="attendance")
    op.drop_index("ix_attendance_exceptions_status", table_name="attendance_exceptions", schema="attendance")
    op.drop_table("attendance_exceptions", schema="attendance")
    op.drop_index("ix_upload_registry_dataset_date", table_name="upload_registry", schema="staging")
    op.drop_index("ix_upload_registry_sha256", table_name="upload_registry", schema="staging")
    op.drop_table("upload_registry", schema="staging")
    op.drop_table("dataset_schema", schema="staging")
    op.drop_table("reporting_hierarchy", schema="hr")
    op.drop_table("holiday_calendar", schema="hr")
    op.drop_table("dim_employee", schema="hr")
    op.drop_table("dim_department", schema="hr")
    op.drop_index("ix_processing_log_run", table_name="processing_log", schema="audit")
    op.drop_table("processing_log", schema="audit")
    op.drop_index("ix_exception_resolution_log_exc", table_name="exception_resolution_log", schema="audit")
    op.drop_table("exception_resolution_log", schema="audit")
    op.drop_table("email_delivery_log", schema="audit")
    op.drop_table("ai_execution_log", schema="audit")
    op.drop_index("ix_processing_run_date", table_name="processing_run", schema="attendance")
    op.drop_table("processing_run", schema="attendance")
