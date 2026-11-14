# Database Design

Target: Microsoft SQL Server. Logical schemas: `staging`, `hr`, `attendance`, `audit`, `security`, `reporting`.
Migration `0001` creates all six schemas on SQL Server so later migrations only add tables.

## Implemented (migration 0001)

| Table | Key | Notes |
|---|---|---|
| `security.app_user` | `user_id` | Usernames are unique and lowercased. Columns: `password_hash` (bcrypt; null reserved for SSO), `failed_login_count`, `locked_until`, `is_active` |
| `security.app_role` | `role_id` | `role_code` unique |
| `security.permission` | `permission_id` | `permission_code` unique |
| `security.user_role` | (`user_id`, `role_id`) | FK to both |
| `security.role_permission` | (`role_id`, `permission_id`) | Rebuilt from `security.yaml` by `init-db` |
| `security.user_department_access` | (`user_id`, `department_code`) | FK to `hr.dim_department` is added once that table exists |
| `audit.user_activity_log` | `activity_id` (BIGINT) | Append-only. No FK to user, so the audit trail outlives user changes. Indexed on `occurred_at` and `user_id` |

All timestamps are `DATETIMEOFFSET`/UTC on SQL Server. Constraint names follow a fixed naming convention (`database/models/base.py`).

## Implemented (migration 0002, Phases 2-12)

| Schema | Tables |
|---|---|
| `staging` | `dataset_schema` (versioned column schemas), `upload_registry` (file, SHA-256, lineage, current/superseded), `upload_row` (raw rows as read), `validation_issue` |
| `hr` | `dim_employee`, `dim_department`, `employee_source_mapping` (VERIFIED / PENDING / REJECTED), `employee_org_history` (effective-dated), `reporting_hierarchy` (effective-dated), `holiday_calendar` |
| `attendance` | `source_attendance`, `attendance_punch`, `leave_record` (standardized, linked to upload), `processing_run` (versioned, input key), `fact_attendance_daily` (one row per run/employee/date), `attendance_reconciliation`, `attendance_exceptions`, `attendance_adjustments` |
| `reporting` | `report_registry` (file + SHA-256 + version + status), `report_approval`, `ai_summary` |
| `audit` | `processing_log`, `exception_resolution_log`, `email_delivery_log` (unique report+recipient), `ai_execution_log` |

Migration 0002 was generated once from the ORM models and frozen; it only creates objects. Every table and index compiles for SQL Server (checked with the MS SQL dialect; against SQL Server 2022 dates are `DATE`, text is `VARCHAR(max)`, timestamps `DATETIMEOFFSET`). **Not yet run against a real SQL Server.** Open point for IT: names are `VARCHAR`; use an `_UTF8` collation or switch to `NVARCHAR` if non-Latin names are expected.

## Planned

Further changes arrive as new, non-destructive migrations.

## Development backend

SQLite (`dev_sqlite`) flattens the schemas with `schema_translate_map` and enforces foreign keys with a PRAGMA. It is not a production substitute and is rejected when `APP_ENV=production`.
**Not yet verified against a real SQL Server** (none is reachable). The first `init-db` against SQL Server is a Phase 7 acceptance item.
