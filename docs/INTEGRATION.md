# Intranet Integration

The platform is built so it can be integrated into the APIS in-house intranet. **Which option to use needs a decision from APIS IT once the intranet's stack and authentication are known.**

## Option A — Intranet calls the REST API (recommended)

The intranet renders its own screens and calls `/api/v1/*`.
- Add the intranet origin to `config/settings.yaml → api.cors_origins` (wildcards are rejected).
- Cross-origin cookies need `SameSite=None; Secure`, or (preferred) an SSO/token flow. See "Authentication" below.
- The API contract is versioned (`/api/v1`) and documented by OpenAPI (`/api/openapi.json` outside production).

## Option B — Embed the React UI

Host the built UI under an intranet path or in an iframe.
- Sub-path hosting: build with `VITE_BASE_PATH=/apps/attendance-mis/ npm run build`.
- Separate API host: build with `VITE_API_BASE=https://mis-api.apis.local`.
- Iframe: add the intranet origin to `api.frame_ancestors`. The CSP header blocks framing by anyone else.

## Option C — Reverse proxy (simplest for users)

The intranet's web server proxies `/attendance-mis/` to this server. It's same-origin, so no CORS and cookies work unchanged.

## Authentication (open decision)

Today: no login page on the local machine (`auth.mode: none`, localhost only), or local accounts with an httpOnly session cookie (`auth.mode: local`). Production must use a real identity. The intended route is the intranet's own sign-in. For intranet single sign-on, the pluggable points are:
- `AppUser.auth_provider` (reserved, default `LOCAL`) and a nullable `password_hash`.
- `api/deps.py → current_principal` is the one place that turns a request into a `Principal`. An SSO variant (Entra ID / OIDC token, or a trusted header set by the intranet proxy) maps the identity to `security.app_user` and keeps the same RBAC.

Not supported, on purpose: exposing session tokens to JavaScript, wildcard CORS, and unauthenticated data endpoints. `/api/health` returns only `{"status": ...}`.

## Machine-to-machine (future)

Scheduled jobs run in-process through `main.py`, so they need no API credentials. If the intranet needs to trigger runs or fetch reports server-side, add service accounts with scoped API keys (not implemented yet).
