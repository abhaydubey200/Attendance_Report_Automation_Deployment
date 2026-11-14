# Changelog

## 0.2.0 — 2026-11-14 — Re-platform to FastAPI + React
- Streamlit UI removed. Added the FastAPI REST API (`api/`, `/api/v1`) and the React + TypeScript UI (`frontend/`, Vite).
- httpOnly cookie sessions (signed, sliding idle expiry), CSRF header guard, security headers, configurable CORS and iframe allowlists for intranet integration.
- Endpoints: auth (login/logout/me with permitted navigation), dashboard summary, system health/config, admin users/roles, public liveness.
- `main.py serve` replaces `run`. The API serves the built UI (single origin).
- New settings `api.*` and env vars `APP_SECRET_KEY`, `API_HOST`, `API_PORT`. Production guards for secret key and secure cookie.
- Tests: 90 backend (19 new API tests) + 8 frontend (Vitest). See docs/INTEGRATION.md for intranet options.

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
