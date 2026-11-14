# APIS Intelligent HR & Attendance MIS

Attendance intelligence, reconciliation and MIS automation platform for APIS India Limited.
Python 3.12 · Streamlit · SQLAlchemy/Alembic · SQL Server (SQLite for local development only).

**Current status: Phase 0 (Discovery) partially complete, Phase 1 (Foundation) complete.**
See [docs/CHANGELOG.md](docs/CHANGELOG.md). The attendance engine is intentionally not built yet.
It waits for real sample datasets and HR-approved rules.

## Quick start (Windows, development)

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
copy .env.example .env                      # optional; defaults use the dev SQLite DB
.\.venv\Scripts\python.exe main.py init-db  # migrations + role/permission seed
.\.venv\Scripts\python.exe main.py create-user --username your.name --role HR_ADMIN --role SYSTEM_ADMIN
.\.venv\Scripts\python.exe main.py check    # config / storage / database health
.\.venv\Scripts\python.exe main.py run      # http://localhost:8501
```

`py` defaults to Python 3.15 on this machine. Always create the venv with `py -3.12`.

HOD users need department scope: `--role HOD --department SALES`.

## Tests

```powershell
.\.venv\Scripts\python.exe -m pytest
```

Tests use temporary directories and a throwaway SQLite database. They never touch `storage/`, `logs/` or real data.

## Layout

| Path | Purpose |
|---|---|
| `app.py` | Streamlit entry (auth gate + permission-aware navigation) |
| `main.py` | Admin CLI: `check`, `init-db`, `create-user`, `run` |
| `config/` | YAML configuration (no secrets) |
| `core/` | Settings loader/validation, logging, paths, time handling |
| `contracts/` | Standardized internal data contracts + lifecycle state machines |
| `database/` | Engine abstraction, ORM models, Alembic migrations, repositories |
| `security/` | Authentication, RBAC authorization, audit |
| `ui/` | Streamlit pages and components |
| `monitoring/` | Health checks |
| `ingestion/`, `data_engine/`, `reporting/`, ... | Packages reserved for later phases |
| `docs/` | Architecture, decisions, rules, test plan, runbooks |

## Ground rules

- No credentials in files. Secrets come from environment variables only.
- No real HR data in git: `storage/`, `logs/`, `*.db`, `*.csv` and `*.xlsx` are ignored.
- Attendance rules and source authority stay **unapproved** (null) until HR signs off. See [docs/ATTENDANCE_RULES.md](docs/ATTENDANCE_RULES.md).
- Dataset column definitions come only from inspected sample files. See [docs/DATA_DICTIONARY.md](docs/DATA_DICTIONARY.md).
- Email distribution and AI are disabled. Config validation refuses email outside production.
