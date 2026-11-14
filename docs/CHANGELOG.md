# Changelog

## 0.1.0 — 2026-11-14 — Phase 0 (partial) + Phase 1 Foundation
- Environment assessment ([PHASE0_DISCOVERY.md](PHASE0_DISCOVERY.md)).
- Project structure, pinned `requirements.txt`, `.env.example`, `.gitignore`.
- Validated YAML configuration for settings, database profiles, RBAC, datasets (pending discovery), attendance rules (draft and unapproved), source authority, recipients and AI (disabled).
- Structured JSON logging with secret redaction and a run_id context.
- Database abstraction (SQL Server and dev SQLite), Alembic migration 0001 (schemas, security tables, user activity audit).
- Local authentication (bcrypt, lockout, audit), RBAC with department scope.
- Provisional data contracts and upload/processing state machines.
- Streamlit shell: login, permission-aware navigation for all PRD pages (placeholders for later phases), executive dashboard empty state, health, configuration and users pages.
- Admin CLI `main.py`: `check`, `init-db`, `create-user`, `run`.
- 135 automated tests.
