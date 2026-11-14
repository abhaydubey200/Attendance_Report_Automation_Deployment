# Architectural Decision Log

| ID | Date | Decision | Rationale |
|---|---|---|---|
| D-001 | 2026-11-14 | Repository root is the project root (not a nested `APIS_INTELLIGENT_HR_MIS/` folder) | Avoids an extra level; the layout matches PRD section 6 otherwise |
| D-002 | 2026-11-14 | Added a `core/` package (settings, logging, paths, time) not listed in the PRD | `config/` holds YAML only; cross-cutting code needed a home that isn't UI or domain |
| D-003 | 2026-11-14 | SQLite `dev_sqlite` profile for development; SQL Server `mssql` profile for real use. SQLite is **rejected when APP_ENV=production** | No SQL Server is reachable from the laptop (PRD 10.1 allows a temporary dev DB behind abstractions) |
| D-004 | 2026-11-14 | Logical schemas (`security`, `audit`, ...) are real SQL Server schemas. On SQLite they are flattened with `schema_translate_map`, and table names are globally unique | One set of models and migrations for both backends |
| D-005 | 2026-11-14 | Alembic for migrations; `main.py init-db` runs them | PRD 10.4 controlled migrations; programmatic entry for tests |
| D-006 | 2026-11-14 | Local bcrypt authentication with lockout (5 failures → 15 min), generic error messages, every attempt audited | "Secure local authentication" option in PRD 18.1. `auth_provider` column reserved for SSO |
| D-007 | 2026-11-14 | RBAC seeded from `config/security.yaml` into `security.*` tables. The principal is **reloaded from the DB on every Streamlit run** | Central store (PRD 3.6). Role changes and deactivation take effect immediately |
| D-008 | 2026-11-14 | Department scope = `ATTENDANCE_VIEW_ALL_DEPARTMENTS` permission OR explicit `user_department_access` rows. Employee-level data needs `ATTENDANCE_VIEW_EMPLOYEE` **and** scope | HOD isolation (PRD 3.3). Directors are aggregate-only by default (PRD 3.4) |
| D-009 | 2026-11-14 | `SYSTEM_ADMIN` holds no HR data permissions | PRD 3.5 |
| D-010 | 2026-11-14 | Every page re-checks its permission server-side; navigation only lists permitted pages | PRD 3.6: hiding navigation is not enough |
| D-011 | 2026-11-14 | Contracts are frozen Pydantic models with `extra="forbid"`, timezone-aware timestamps required, `CONTRACT_VERSION = 0.1.0-provisional` | Explicit, versioned contracts (PRD 6.2). Field sets are confirmed in Phase 4 |
| D-012 | 2026-11-14 | Leave defaults to `UNKNOWN` approval status, and only `APPROVED` counts as approved | PRD 8.6: pending or unknown leave must never silently become approved |
| D-013 | 2026-11-14 | All HR policy values in `attendance_rules.yaml` are `null`. Health check and dashboard flag them as PROVISIONAL | PRD section 15: do not invent rules |
| D-014 | 2026-11-14 | Streamlit binds to `localhost` and hides error details in the browser | Dev laptop should not expose HR data on the network. Production sets the address explicitly |
| D-015 | 2026-11-14 | Storage is UTC (`DateTime(timezone=True)`). Display and business dates use Asia/Kolkata | Unambiguous timestamps. SQLite returns naive values, normalised by `ensure_utc` |
