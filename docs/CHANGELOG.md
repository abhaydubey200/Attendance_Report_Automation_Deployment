# Changelog

## 0.5.0 - 2026-11-14 - Pocket HRMS AttendanceSummary (Pocket HRMS only)
- Direction from APIS: manual upload only for now; all data comes from Pocket HRMS. Bizom dataset switched off (kept for later).
- New dataset `HRMS_ATTENDANCE_SUMMARY` for the Pocket HRMS "AttendanceSummary" export, modelled on the first real sample: header found automatically below the preamble, the two rows per employee (in time, out time) paired into one record, Remarks dropped.
- Factual labels per record (PUNCH_IN_OUT, PUNCH_SINGLE, NO_PUNCH, NO_PUNCH_NO_SHIFT, LEAVE:<code>); their meaning is an editable value map. Seeded proposal: PUNCH_IN_OUT=PRESENT, PUNCH_SINGLE=MISSING_PUNCH, LEAVE:PL/SL=APPROVED_LEAVE; NO_PUNCH, NO_PUNCH_NO_SHIFT and LEAVE:LD left UNRESOLVED for HR.
- The summary also builds the employee list; Category becomes the reporting group (HOD reports per category).
- Exclusion patterns for test/dummy codes (skipped rows do not force a review); unmapped values reported once per value with a count.
- `init-db` seeds a dataset's first schema from `datasets.yaml` (never overwrites an existing one). Demo rebuilt on the new format.
- Verified with the real sample in a throwaway database (deleted afterwards): 721 employees, 126 present, 2 approved leave, 593 awaiting HR decisions, reports for 4 categories.
- Tests: 174 backend, 11 frontend.

## 0.4.0 - 2026-11-14 - Phases 2-12
- Phase 2-3: upload inspection (type/size/signature/macro/encryption), CSV/XLSX reader, preview, schema and content validation with structured issues, exception CSV, SHA-256 duplicate prevention, supersede and controlled reprocessing, read-only raw archive.
- Column-schema discovery: map a real sample file's columns in the Dataset Registry; versioned schemas.
- Phase 4: adapters to contracts, standardized hr/attendance tables, employee mapping (exact code, manual review, name suggestions only), effective-dated department history.
- Phase 5-6: deterministic engine with provisional precedence, KPIs (percentages withheld until rules approved), versioned idempotent runs, stage logging, resume, reconciliation (8 categories) and exception workflow with adjustments.
- Phase 7: migration 0002 (25 tables); SQL Server DDL compile check.
- Phase 8: HOD, Directors and HR/Admin reports in XLSX and HTML with PROVISIONAL banner, registry, checksums, approval, scoped download.
- Phase 9: dashboard, daily/department/absenteeism/leave/missing-punch/employee analytics, data quality; all scoped.
- Phase 10: email distribution via outbox (test), SMTP or Microsoft Graph, with approval, recipient, duplicate and retry controls.
- Phase 11-12: optional Ollama summary with number grounding and fallback; template-based attendance analyst.
- UI: 30 working pages; `main.py process` and `main.py demo`.
- Tests: 165 backend, 11 frontend.

## 0.3.0 — 2026-11-14 — No login page + APIS India branding
- `auth.mode: none` (new default): no login page. The app acts as the configured local operator. Localhost only, refused in production. `local` sign-in mode kept (`AUTH_MODE=local`).
- APIS India Limited UI: honey-gold top bar with "apis" oval wordmark, espresso navigation, cream workspace, Literata/Jost typography (bundled), honeycomb motif, gold-accented tables and KPI cards. Responsive header.
- Unreachable-server screen instead of a login form. Fonts never inlined (CSP `font-src 'self'`).
- Tests: 99 backend + 10 frontend.

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
