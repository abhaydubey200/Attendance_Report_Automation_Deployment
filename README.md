# APIS Intelligent HR & Attendance MIS

Attendance intelligence, reconciliation and MIS **automation** platform for APIS India Limited.

**Stack:** Python 3.12 automation core and FastAPI REST API · React 19 + TypeScript (Vite) UI · SQLAlchemy/Alembic · SQL Server (SQLite for local development only).

The automation runs headless (CLI / scheduler). The REST API exposes it to the React UI now and to the **APIS intranet** later. See [docs/INTEGRATION.md](docs/INTEGRATION.md).

**Status:** Phase 1 (Foundation) is complete, re-platformed from Streamlit to FastAPI + React (v0.2.0). The attendance engine waits for sample datasets and HR-approved rules.

## Quick start (Windows, development)

One-time setup:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
npm --prefix frontend install
.\.venv\Scripts\python.exe main.py init-db
.\.venv\Scripts\python.exe main.py create-user --username your.name --role HR_ADMIN --role SYSTEM_ADMIN
```

**Day-to-day development** (two terminals; the UI hot-reloads and proxies `/api` to the API):

```powershell
.\.venv\Scripts\python.exe main.py serve --reload     # API on http://127.0.0.1:8000  (docs: /api/docs)
npm --prefix frontend run dev                          # UI  on http://localhost:5173
```

**Single-server mode** (how it is deployed): build the UI once, and the API serves it.

```powershell
npm --prefix frontend run build
.\.venv\Scripts\python.exe main.py serve              # UI + API on http://127.0.0.1:8000
```

`py` defaults to Python 3.15 on this machine. Always create the venv with `py -3.12`.

## Tests

```powershell
.\.venv\Scripts\python.exe -m pytest      # backend: config, contracts, DB, auth, RBAC, API
npm --prefix frontend test                 # frontend: login flow, navigation, formatting
npm --prefix frontend run typecheck
```

## Layout

| Path | Purpose |
|---|---|
| `main.py` | CLI: `check`, `init-db`, `create-user`, `serve` |
| `api/` | FastAPI app factory, session cookies, routers (`/api/v1/...`), page registry |
| `frontend/` | React + TypeScript UI (Vite). `npm run build` writes `frontend/dist/`, which the API serves |
| `config/` | YAML configuration (no secrets) |
| `core/` | Settings loader and validation, logging, paths, time handling |
| `contracts/` | Standardized internal data contracts and lifecycle state machines |
| `database/` | Engine abstraction, ORM models, Alembic migrations, repositories |
| `security/` | Authentication, RBAC authorization, audit |
| `monitoring/` | Health checks |
| `ingestion/`, `data_engine/`, `reporting/`, `orchestration/`, ... | Automation modules (later phases) |
| `docs/` | Architecture, decisions, integration, rules, test plan, runbooks |

## Ground rules

- No credentials in files. Secrets (DB credentials, `APP_SECRET_KEY`) come from environment variables only.
- No real HR data in git: `storage/`, `logs/`, `*.db`, `*.csv` and `*.xlsx` are ignored.
- Attendance rules and source authority stay **unapproved** (null) until HR signs off. See [docs/ATTENDANCE_RULES.md](docs/ATTENDANCE_RULES.md).
- Dataset column definitions come only from inspected sample files.
- Email and AI are disabled. Configuration validation refuses email outside production.
