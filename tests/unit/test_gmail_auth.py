"""Gmail API one-time sign-in helper. No network: Google is simulated."""

from __future__ import annotations

import base64
import json
import threading
import time
from urllib.parse import parse_qs, urlparse

import httpx
import pytest

from daily import gmail_auth as ga

CLIENT = ga.Client("cid.apps.googleusercontent.com", "test-secret")


def test_client_from_env_and_json(tmp_path):
    assert ga.client_from({"GMAIL_CLIENT_ID": "a", "GMAIL_CLIENT_SECRET": "b"}) == ga.Client("a", "b")
    f = tmp_path / "client.json"
    f.write_text(json.dumps({"web": {"client_id": "x", "client_secret": "y"}}))
    assert ga.client_from({}, f) == ga.Client("x", "y")
    with pytest.raises(ga.GmailAuthError, match="GMAIL_CLIENT_ID"):
        ga.client_from({})


def test_auth_url_asks_only_for_send_offline_with_pkce():
    verifier, challenge = ga.pkce()
    q = {k: v[0] for k, v in parse_qs(urlparse(ga.auth_url(CLIENT, "http://localhost:8765/oauth2callback", "st", challenge)).query).items()}
    assert q["scope"] == "https://www.googleapis.com/auth/gmail.send openid email"
    assert (q["access_type"], q["prompt"], q["code_challenge_method"], q["state"]) == ("offline", "consent", "S256", "st")
    assert q["redirect_uri"] == "http://localhost:8765/oauth2callback" and len(verifier) > 43


def test_exchange_returns_refresh_token_and_mailbox(monkeypatch):
    payload = base64.urlsafe_b64encode(json.dumps({"email": "attendance@example.com"}).encode()).decode().rstrip("=")
    sent = {}

    def fake_post(url, data, timeout):
        sent.update(data)
        return httpx.Response(200, json={"refresh_token": "r-tok", "access_token": "a", "id_token": f"h.{payload}.s"})

    monkeypatch.setattr(httpx, "post", fake_post)
    assert ga.exchange(CLIENT, "code1", "http://localhost/cb", "ver") == ("r-tok", "attendance@example.com")
    assert sent["code_verifier"] == "ver" and sent["grant_type"] == "authorization_code"
    monkeypatch.setattr(httpx, "post", lambda *a, **k: httpx.Response(200, json={"access_token": "a"}))
    with pytest.raises(ga.GmailAuthError, match="no refresh token"):
        ga.exchange(CLIENT, "c", "r", "v")


def test_set_env_value_replaces_commented_or_existing_line(tmp_path):
    env = tmp_path / ".env"
    env.write_text("# header\nGMAIL_CLIENT_ID=x\n# GMAIL_REFRESH_TOKEN=\nOTHER=1\n")
    ga.set_env_value(env, "GMAIL_REFRESH_TOKEN", "tok")
    ga.set_env_value(env, "NEW_KEY", "v")
    assert env.read_text().splitlines() == ["# header", "GMAIL_CLIENT_ID=x", "GMAIL_REFRESH_TOKEN=tok", "OTHER=1", "NEW_KEY=v"]
    with pytest.raises(ValueError):
        ga.set_env_value(env, "K", "a\nb")


@pytest.mark.parametrize("query, expected", [("state=good&code=abc", "abc"), ("state=bad&code=abc", "State mismatch")])
def test_local_callback(query, expected):
    port = 18765 + (0 if "good" in query else 1)

    def browser():
        time.sleep(0.3)
        httpx.get(f"http://127.0.0.1:{port}/favicon.ico")          # ignored
        httpx.get(f"http://127.0.0.1:{port}/oauth2callback?{query}")

    threading.Thread(target=browser, daemon=True).start()
    if expected == "abc":
        assert ga.wait_for_code(port, "good", timeout=10) == "abc"
    else:
        with pytest.raises(ga.GmailAuthError, match=expected):
            ga.wait_for_code(port, "good", timeout=10)
