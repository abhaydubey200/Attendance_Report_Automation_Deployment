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

## Planned

The tables in PRD 10.3 for staging, hr, attendance, reporting and the remaining audit tables arrive in their phases. Each one comes as a new, non-destructive migration.

## Development backend

SQLite (`dev_sqlite`) flattens the schemas with `schema_translate_map` and enforces foreign keys with a PRAGMA. It is not a production substitute and is rejected when `APP_ENV=production`.
**Not yet verified against a real SQL Server** (none is reachable). The first `init-db` against SQL Server is a Phase 7 acceptance item.
