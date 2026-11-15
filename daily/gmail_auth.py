"""One-time Gmail API sign-in for the sender mailbox (``main.py gmail-auth``).

Opens Google's consent page in the browser; the person signs in AS THE SENDER MAILBOX (e.g. attendance@...)
and allows "send email on your behalf". Google redirects back to http://localhost:<port>/oauth2callback, the
code is exchanged for a refresh token (PKCE + state check) and the token is written to the local .env file
as GMAIL_REFRESH_TOKEN. It is never printed or stored anywhere else.

Scope: gmail.send only (cannot read mail) + openid email (to show which mailbox signed in).
For a "web" OAuth client the redirect URI must be listed in Google Cloud Console -> Credentials ->
the OAuth client -> Authorized redirect URIs.
"""

from __future__ import annotations

import base64
import hashlib
import json
import re
import secrets
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse

import httpx

AUTH_URI = "https://accounts.google.com/o/oauth2/auth"
TOKEN_URI = "https://oauth2.googleapis.com/token"
SCOPES = "https://www.googleapis.com/auth/gmail.send openid email"


class GmailAuthError(Exception):
    pass


@dataclass
class Client:
    client_id: str
    client_secret: str


def client_from(env: dict, client_json: Path | None = None) -> Client:
    if client_json:
        data = json.loads(client_json.read_text(encoding="utf-8"))
        block = data.get("web") or data.get("installed") or {}
        if not block.get("client_id") or not block.get("client_secret"):
            raise GmailAuthError("The JSON file has no client_id / client_secret (download it from Google Cloud -> Credentials).")
        return Client(block["client_id"], block["client_secret"])
    cid, secret = env.get("GMAIL_CLIENT_ID", ""), env.get("GMAIL_CLIENT_SECRET", "")
    if not cid or not secret:
        raise GmailAuthError("Set GMAIL_CLIENT_ID and GMAIL_CLIENT_SECRET in .env, or pass --client-json.")
    return Client(cid, secret)


def pkce() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    return verifier, challenge


def auth_url(client: Client, redirect_uri: str, state: str, challenge: str, login_hint: str | None = None) -> str:
    params = {"client_id": client.client_id, "redirect_uri": redirect_uri, "response_type": "code", "scope": SCOPES,
              "access_type": "offline", "prompt": "consent", "include_granted_scopes": "true", "state": state,
              "code_challenge": challenge, "code_challenge_method": "S256"}
    if login_hint:
        params["login_hint"] = login_hint
    return f"{AUTH_URI}?{urlencode(params)}"


def exchange(client: Client, code: str, redirect_uri: str, verifier: str) -> tuple[str, str | None]:
    """-> (refresh_token, email of the signed-in mailbox)."""
    try:
        r = httpx.post(TOKEN_URI, data={"grant_type": "authorization_code", "code": code, "client_id": client.client_id,
                                        "client_secret": client.client_secret, "redirect_uri": redirect_uri,
                                        "code_verifier": verifier}, timeout=30)
    except httpx.HTTPError as exc:
        raise GmailAuthError(f"Could not reach Google: {type(exc).__name__}") from exc
    if r.status_code >= 400:
        raise GmailAuthError(f"Google refused the sign-in code ({r.status_code}): {r.json().get('error_description') or r.text[:200]}")
    body = r.json()
    if not body.get("refresh_token"):
        raise GmailAuthError("Google returned no refresh token. Remove the app's access at myaccount.google.com/permissions and run again.")
    return body["refresh_token"], _email_from_id_token(body.get("id_token"))


def _email_from_id_token(token: str | None) -> str | None:
    # Received directly from Google's token endpoint over TLS, so the payload is only read, not verified.
    if not token or token.count(".") != 2:
        return None
    payload = token.split(".")[1]
    try:
        return json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4))).get("email")
    except (ValueError, json.JSONDecodeError):
        return None


def set_env_value(path: Path, key: str, value: str) -> None:
    """Replace or add KEY=value in a .env file, keeping everything else (comments, order)."""
    if "\n" in value or "\r" in value:
        raise ValueError("Value must be one line.")
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    pattern = re.compile(rf"^\s*#?\s*{re.escape(key)}\s*=")
    for i, line in enumerate(lines):
        if pattern.match(line):
            lines[i] = f"{key}={value}"
            break
    else:
        lines.append(f"{key}={value}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def wait_for_code(port: int, state: str, timeout: int = 300) -> str:
    """Serve one request on localhost:<port>/oauth2callback and return the authorization code."""
    result: dict = {}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            url = urlparse(self.path)
            if url.path != "/oauth2callback":
                self.send_response(404)
                self.end_headers()
                return
            q = {k: v[0] for k, v in parse_qs(url.query).items()}
            if q.get("state") != state:
                result["error"] = "State mismatch - start again."
            elif "error" in q:
                result["error"] = f"Google: {q['error']}"
            else:
                result["code"] = q.get("code")
            ok = "code" in result
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(("<h2>APIS Daily Attendance</h2><p>" + ("Gmail is connected. You can close this tab."
                              if ok else "Sign-in did not complete. Check the terminal.") + "</p>").encode())

        def log_message(self, *_):  # keep the code out of logs
            pass

    import time

    server = HTTPServer(("127.0.0.1", port), Handler)
    server.timeout = 5
    deadline = time.monotonic() + timeout
    try:
        while not result:                      # other requests (e.g. /favicon.ico) are answered 404 and ignored
            if time.monotonic() > deadline:
                raise GmailAuthError("Timed out waiting for the Google sign-in.")
            server.handle_request()
    finally:
        server.server_close()
    if "error" in result:
        raise GmailAuthError(result["error"])
    return result["code"]
