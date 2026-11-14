# Phase 0 — Discovery

Assessed 2026-11-14 on the development laptop.

## Environment findings

| Item | Finding | Impact |
|---|---|---|
| Repository | Empty folder; `git init` done, nothing committed | Greenfield |
| OS | Windows 11 Pro 10.0.26300 | — |
| Python | 3.12.10 at `%LOCALAPPDATA%\Programs\Python\Python312`. **`py` defaults to 3.15**, and a 32-bit 3.15 is also installed | Always use `py -3.12` / the `.venv` |
| pip | Works through `python -m pip`. Running `pip.exe` directly gave *Permission denied* (application control, presumably) | Use `python -m pip` |
| Packages | All of `requirements.txt` installed into `.venv` and imported cleanly | No blocked dependencies so far |
| SQL Server | No local instance, no `sqlcmd` | Dev uses SQLite behind the abstraction (see DECISIONS.md D-003) |
| ODBC drivers | Only the legacy **"SQL Server"** (SQLSRV32) driver. No *ODBC Driver 17/18 for SQL Server* | **IT action:** install ODBC Driver 18 for SQL Server before connecting to a real instance |
| Storage | Project folder and temp dir are writable | — |
| RAM | 8 GB (per PRD) | AI stays disabled |

## Still open (blocks Phase 2+)

1. **Sample files** for each of the 8 dataset categories (anonymised or synthetic). They are needed to define columns in `config/datasets.yaml`.
2. **SQL Server**: host, database name, authentication mode, a least-privilege login, and whether the database shares a server with the app.
3. **HR decisions** listed in [ATTENDANCE_RULES.md](ATTENDANCE_RULES.md) and the source-authority matrix.
4. **Department codes** and the HOD → department assignment list.
5. Confirmation of the enterprise authentication route (local accounts now; Entra ID SSO possible later).
