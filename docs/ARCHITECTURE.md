# Architecture

A modular monolith (PRD 18.2). Dependencies point inward:

```
ui/ (Streamlit) ──► security/ ──► database/repositories ──► database/models
   │                   │
   └──► monitoring/    └──► core/ (config, logging, time) ◄── contracts/
```

- **core**: loads and validates every YAML file into Pydantic models. Applies environment overrides and environment rules (no SQLite or email misuse). Provides structured JSON logging with secret redaction and a `run_id` context variable.
- **contracts**: source-agnostic records (employee, attendance, leave, punch, department) and the upload and processing state machines. Manual adapters and future connectors must both emit these.
- **database**: `create_db_engine(settings)` is the only engine factory. `session_scope()` gives one transaction per unit of work. Alembic migrations live in `database/migrations`.
- **security**: bcrypt authentication with lockout and audit. Authorization helpers (`require_permission`, `require_department_access`, `can_view_employee_records`) must be called before any data access.
- **ui**: `app.py` checks DB readiness, then authentication, then permission-filtered `st.navigation`. Each page body calls `require_permission` again.
- **monitoring**: health checks shared by the CLI and the System Monitoring pages.

## Request flow (Streamlit run)

1. Settings and engine come from `st.cache_resource` (one per process).
2. `check_database`: if migrations are missing, the app stops with an instruction.
3. `current_principal()` checks the idle timeout and reloads the principal from the DB. A deactivated user is signed out.
4. Navigation is built from `PAGES` filtered by permission.
5. The page renders. An `AuthorizationError` produces a generic denial and a log entry.

## Later phases plug in at

`ingestion/` (Phase 2–3) → `data_engine/` (Phase 4–6) → `reporting/` (Phase 8) → `email_engine/`, `ai_engine/`, `connectors/` (Phase 10–13), coordinated by `orchestration/`.
