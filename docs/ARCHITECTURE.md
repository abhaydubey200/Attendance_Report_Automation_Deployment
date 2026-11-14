# Architecture

A modular monolith (PRD 18.2), API-first, with the automation core kept separate from any UI.

```
                 ┌──────────────── React UI (frontend/, Vite + TS) ───────────────┐
                 │ login · permission-driven navigation · dashboard · admin pages │
                 └──────────────────────────────┬─────────────────────────────────┘
 APIS intranet (future) ──── HTTPS /api/v1 ─────┤
                                                ▼
                         FastAPI (api/)  — sessions, RBAC guards, JSON schemas
                                                │
     CLI / Windows Task Scheduler (main.py) ────┤   ← headless automation entry point
                                                ▼
   ingestion/ → data_engine/ → reporting/ → email_engine/ / ai_engine/   (Phases 2–12)
                                                │
              security/ · contracts/ · core/ (config, logging, time) · monitoring/
                                                │
                         database/ (SQLAlchemy, Alembic) → SQL Server
```

## Principles

- **The automation does not depend on the UI.** Ingestion, processing and reporting are Python modules called by the CLI and scheduler. The API is a thin layer that triggers them and reads their results. The React UI and the future intranet are both API clients.
- **One authorization model.** Every API route declares `require(Perm.X)`. The UI hides pages the API doesn't list, but it is never the enforcement point.
- **Versioned API** under `/api/v1`. The OpenAPI schema is at `/api/openapi.json` (disabled in production), and the frontend types in `frontend/src/api/types.ts` mirror `api/schemas.py`.

## Modules

- **core**: validated YAML settings with environment overrides and guards (no SQLite/email/insecure cookies in production, no secrets in YAML). Structured JSON logging with redaction and a `run_id` context.
- **contracts**: source-agnostic records and the upload/processing state machines.
- **database**: `create_db_engine(settings)` is the only engine factory. `session_scope()` is one transaction per unit of work. Alembic migrations.
- **security**: bcrypt authentication with lockout and audit. Authorization helpers.
- **api**: `create_app()` factory, httpOnly session cookie (`api/sessions.py`), dependencies (`api/deps.py`), routers, server-side page registry (`api/navigation.py`). Serves `frontend/dist` when built.
- **frontend**: React Router app. `AuthProvider` holds the profile from `/auth/me`. Pages call `useApi()`. Any 401 returns to login.
- **monitoring**: health checks shared by the CLI and `/api/v1/system/health`.

## Request flow

1. The browser sends the session cookie (httpOnly, SameSite=Strict) and `X-APIS-Request: 1`.
2. Middleware rejects unsafe methods without that header (CSRF guard) and adds security headers.
3. `current_principal` verifies the token, **reloads the principal from the DB** (a deactivated user gets 401), and slides the idle expiry.
4. `require(perm)` raises `AuthorizationError`, which becomes 403 `{"detail":"Not authorised"}`.
5. The route returns a Pydantic model. Responses are `Cache-Control: no-store`.
