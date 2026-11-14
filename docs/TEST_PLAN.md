# Test Plan

Run: `.\.venv\Scripts\python.exe -m pytest` (backend) and `npm --prefix frontend test` (frontend). All fixtures are synthetic (`TEST-0001`-style codes) and isolated in temp directories.

## Phase 1 coverage (90 backend + 8 frontend tests, all passing on 2026-11-14, v0.2.0)

| Area | File | Covers |
|---|---|---|
| Configuration | `tests/unit/test_config.py` | All shipped YAML is valid. Production needs a secret key and secure cookie. No secret in YAML. Wildcard CORS rejected. Env overrides. Production rejects SQLite. Email blocked outside prod. AI needs a model. Unknown permissions and profiles are rejected. Rules are unapproved and null. Source authority is validated. No invented dataset columns |
| Logging | `tests/unit/test_logging.py` | Inline and field secret redaction, JSON format with run_id, file handler, idempotent setup |
| Contracts | `tests/unit/test_contracts.py` | Strict, immutable, tz-aware. Only APPROVED leave counts. Effective dating. Upload lifecycle cannot skip validation. Processing transitions (AI failure ≠ run failure, approval before distribution) |
| DB URL | `tests/unit/test_database_connection.py` | mssql URL building, SQL and trusted auth, password not rendered |
| DB integration | `tests/integration/test_database.py` | Migrations idempotent, role sync idempotent, rollback on error, unique usernames, FK enforcement |
| Authentication | `tests/security/test_authentication.py` | Hashing, policy, success and failure audit, lockout and expiry, inactive users |
| Authorization | `tests/security/test_authorization.py` | HOD isolation, Director aggregate-only, SYSTEM_ADMIN without HR data, anonymous, immediate deactivation, DB-driven permission changes |
| REST API | `tests/integration/test_api.py` | 401 without session. Login cookie flags. Generic failures. Lockout over HTTP. CSRF header. Logout. Tampered, foreign and expired tokens. Immediate deactivation. HOD/SYSTEM_ADMIN 403s. No secrets in responses. Security headers. Docs off in production. Navigation filtering. SPA fallback and traversal |
| Frontend | `frontend/src/*.test.ts(x)` | Login screen, failed login message, successful login renders permitted nav and dashboard, CSRF header and credentials sent, unlisted pages not routable, planned pages, 401 returns to login. IST date formatting |
| Health / CLI | `tests/unit/test_health_and_cli.py` | Health checks, `init-db`, `check`, `create-user` validation |

## Not yet covered
- A real SQL Server (`-m mssql` marker is reserved; needs `DB_PROFILE=mssql` and a reachable instance).
- The 20 mandatory edge cases in PRD 23.5. These come with the attendance engine and need HR rules.
