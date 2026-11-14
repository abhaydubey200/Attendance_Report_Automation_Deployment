# Security Design

## Access modes
- `auth.mode: none` (default, development): no login page. Requests act as `auth.default_user` (roles validated against `security.yaml`, permissions loaded from the DB). Guardrails: the server must bind to localhost (checked in config and in `main.py serve`), and the mode is rejected when `APP_ENV=production`. Audit records carry the operator username.
- `auth.mode: local`: username/password sign-in, described below.
- Planned: intranet sign-in (trusted identity from the APIS intranet), replacing both for production.

## Authentication (local mode)
- Local accounts with bcrypt (cost 12). Policy: at least 12 characters, at most 72 bytes, and three of four character classes.
- 5 consecutive failures lock the account for 15 minutes (`settings.yaml: session`).
- Every login attempt (success, failure, denial) is written to `audit.user_activity_log`. Passwords are never stored or logged.
- Unknown usernames take the same bcrypt time as known ones, so user enumeration by timing is not possible.
- Session: signed JWT in an **httpOnly, SameSite=Strict** cookie (`Secure` enforced in production), 30-minute sliding idle timeout. The principal is reloaded from the DB on every request, so deactivation is immediate. `APP_SECRET_KEY` (at least 32 characters) is required in production.
- CSRF: unsafe methods require `X-APIS-Request: 1`. CORS is off by default; origins are allowlisted, and wildcards are rejected.
- Users are created only through the CLI (`main.py create-user`) in Phase 1, and the password prompt is never echoed.

## Authorization (RBAC)
- Six roles and 21 permissions are defined in `config/security.yaml` (marked PROVISIONAL until HR/IT approve) and synced into `security.*` tables.
- Scope: `ATTENDANCE_VIEW_ALL_DEPARTMENTS`, or explicit department grants.
- Employee-level data requires the permission **and** department scope.
- `SYSTEM_ADMIN` cannot see HR data. `DIRECTOR` sees aggregates only.
- Every API route declares its permission (`require(Perm.X)`), so a missing permission returns 403. UI navigation comes from the server page registry and is never the enforcement point.

## Secrets and data
- DB credentials come from environment variables only. Connection URLs are never logged.
- The log redaction filter masks `password`, `token`, `secret`, `api_key` and similar keys and inline values.
- `.gitignore` excludes `.env`, `storage/`, `logs/`, databases, and CSV/XLSX files outside test fixtures.
- The API binds to 127.0.0.1 by default and returns generic error bodies. Headers: CSP (`frame-ancestors` allowlist), `nosniff`, `Referrer-Policy: same-origin`, `Cache-Control: no-store` on `/api/*`. OpenAPI docs are disabled in production. The SPA file server refuses path traversal.

## Phase 2-12 controls
- Uploads: extension, size, signature, encryption, macro and archive checks; formulas never evaluated; raw files archived read-only; SHA-256 duplicate detection; reprocessing needs DATA_REGISTRY_MANAGE.
- Analytics, exceptions and reports are scoped to the caller's departments on the server; out-of-scope employees return "not found".
- Report downloads re-verify the stored SHA-256; HTML previews are served with a sandbox CSP and shown in a sandboxed iframe.
- Email: only approved reports of an approved run; real delivery needs production + `features.email_enabled` + HR-approved recipients; otherwise outbox test mode with `[TEST]` subjects; one delivery per report and recipient.
- AI: aggregated metrics only (no names or codes); output rejected if it contains numbers not in the metrics; the analyst uses fixed query templates (no generated SQL), respects scope and logs every question.

## Open items
- Windows ACLs on production `storage/`, `logs/` (IT).
- Enterprise SSO (Entra ID) evaluation.
- Least-privilege SQL logins (separate migration/owner login vs runtime login).
