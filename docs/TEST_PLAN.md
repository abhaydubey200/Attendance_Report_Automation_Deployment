# Test Plan

Run: `.\.venv\Scripts\python.exe -m pytest`. All fixtures are synthetic (`TEST-0001`-style codes) and isolated in temp directories.

## Phase 1 coverage (135 tests, all passing on 2026-11-14)

| Area | File | Covers |
|---|---|---|
| Configuration | `tests/unit/test_config.py` | All shipped YAML is valid. Env overrides. Production rejects SQLite. Email blocked outside prod. AI needs a model. Unknown permissions and profiles are rejected. Rules are unapproved and null. Source authority is validated. No invented dataset columns |
| Logging | `tests/unit/test_logging.py` | Inline and field secret redaction, JSON format with run_id, file handler, idempotent setup |
| Contracts | `tests/unit/test_contracts.py` | Strict, immutable, tz-aware. Only APPROVED leave counts. Effective dating. Upload lifecycle cannot skip validation. Processing transitions (AI failure ≠ run failure, approval before distribution) |
| DB URL | `tests/unit/test_database_connection.py` | mssql URL building, SQL and trusted auth, password not rendered |
| DB integration | `tests/integration/test_database.py` | Migrations idempotent, role sync idempotent, rollback on error, unique usernames, FK enforcement |
| Authentication | `tests/security/test_authentication.py` | Hashing, policy, success and failure audit, lockout and expiry, inactive users |
| Authorization | `tests/security/test_authorization.py` | HOD isolation, Director aggregate-only, SYSTEM_ADMIN without HR data, anonymous, immediate deactivation, DB-driven permission changes |
| App shell | `tests/integration/test_app_shell.py` | Uninitialised DB blocks the app. Login gate, failed and successful login. Admin landing. Navigation filtering |
| Page access | `tests/integration/test_pages_render.py` | Each of the 31 pages renders when authorised and shows only a denial when not |
| Health / CLI | `tests/unit/test_health_and_cli.py` | Health checks, `init-db`, `check`, `create-user` validation |

## Not yet covered
- A real SQL Server (`-m mssql` marker is reserved; needs `DB_PROFILE=mssql` and a reachable instance).
- The 20 mandatory edge cases in PRD 23.5. These come with the attendance engine and need HR rules.
