# Deployment Guide

Development setup is covered in the README. Production (Phase 14) needs, per environment:

1. Python 3.12 x64 and `pip install -r requirements.txt` into a venv.
2. **Microsoft ODBC Driver 18 for SQL Server** (not installed on the dev laptop today).
3. Environment variables: `APP_ENV=production`, `DB_PROFILE=mssql`, `DB_HOST`, `DB_NAME`, and either `DB_TRUSTED_CONNECTION=yes` (service account) or `DB_USER`/`DB_PASSWORD`. Set `APP_STORAGE_DIR` and `APP_LOG_DIR` to ACL-restricted locations.
4. `python main.py init-db` with a login allowed to create schemas and tables. Runtime should use a lower-privilege login.
5. `python main.py check` must show no FAIL.
6. Streamlit `server.address` set for the host's interface, behind HTTPS (reverse proxy) as IT directs.

Separate configuration, credentials, storage, recipients and logs per environment (PRD 24.3). Email stays disabled until HR approval.
