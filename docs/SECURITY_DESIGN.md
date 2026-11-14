# Security Design

## Authentication
- Local accounts with bcrypt (cost 12). Policy: at least 12 characters, at most 72 bytes, and three of four character classes.
- 5 consecutive failures lock the account for 15 minutes (`settings.yaml: session`).
- Every login attempt (success, failure, denial) is written to `audit.user_activity_log`. Passwords are never stored or logged.
- Unknown usernames take the same bcrypt time as known ones, so user enumeration by timing is not possible.
- 30-minute idle timeout. The principal is reloaded from the DB on every run, so deactivation is immediate.
- Users are created only through the CLI (`main.py create-user`) in Phase 1, and the password prompt is never echoed.

## Authorization (RBAC)
- Six roles and 21 permissions are defined in `config/security.yaml` (marked PROVISIONAL until HR/IT approve) and synced into `security.*` tables.
- Scope: `ATTENDANCE_VIEW_ALL_DEPARTMENTS`, or explicit department grants.
- Employee-level data requires the permission **and** department scope.
- `SYSTEM_ADMIN` cannot see HR data. `DIRECTOR` sees aggregates only.
- Navigation is filtered by permission, and every page also calls `require_permission` server-side.

## Secrets and data
- DB credentials come from environment variables only. Connection URLs are never logged.
- The log redaction filter masks `password`, `token`, `secret`, `api_key` and similar keys and inline values.
- `.gitignore` excludes `.env`, `storage/`, `logs/`, databases, and CSV/XLSX files outside test fixtures.
- Streamlit binds to localhost, hides error details, keeps XSRF protection on and turns usage stats off.

## Open items
- Windows ACLs on production `storage/`, `logs/` (IT).
- Enterprise SSO (Entra ID) evaluation.
- Least-privilege SQL logins (separate migration/owner login vs runtime login).
