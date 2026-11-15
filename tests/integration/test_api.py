"""REST API: sign-in, no-login mode, access control, security headers, SPA serving."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from api.main import CSRF_HEADER, create_app
from api.navigation import PAGES, visible_pages
from security.permissions import Perm, Principal
from tests.conftest import TEST_PASSWORD

H = {CSRF_HEADER: "1"}


def with_auth_mode(settings, mode: str):
    return settings.model_copy(update={"auth": settings.auth.model_copy(update={"mode": mode})})


@pytest.fixture
def client(settings, engine, tmp_path):
    """Sign-in mode client."""
    with TestClient(create_app(with_auth_mode(settings, "local"), engine, frontend_dist=tmp_path / "no-dist")) as c:
        yield c


@pytest.fixture
def open_client(settings, engine, tmp_path):
    """No-login mode (the shipped default)."""
    with TestClient(create_app(settings, engine, frontend_dist=tmp_path / "no-dist")) as c:
        yield c


def login(client: TestClient, username: str, password: str = TEST_PASSWORD):
    return client.post("/api/v1/auth/login", json={"username": username, "password": password}, headers=H)


def test_liveness_is_public_and_minimal(client):
    r = client.get("/api/health")
    assert r.status_code == 200 and r.json() == {"status": "ok"}


def test_protected_endpoints_require_login(client):
    for path in ("/api/v1/auth/me", "/api/v1/days", "/api/v1/emails", "/api/v1/settings"):
        assert client.get(path).status_code == 401, path


def test_login_sets_httponly_cookie_and_returns_navigation(client, make_user, settings):
    make_user("hr.user", ["HR"])
    r = login(client, "HR.User")
    assert r.status_code == 200
    body = r.json()
    assert body["roles"] == ["HR"] and {p["slug"] for p in body["navigation"]} == {"upload", "insights", "mail", "emails", "reports", "employee-report", "employees"}
    cookie = r.headers["set-cookie"].lower()
    assert settings.api.cookie_name in cookie and "httponly" in cookie and "samesite=strict" in cookie


def test_bad_login_is_generic_and_sets_no_cookie(client, make_user):
    make_user("user1", ["VIEWER"])
    for username in ("user1", "nobody"):
        r = login(client, username, "wrong")
        assert r.status_code == 401 and "Invalid username or password" in r.json()["detail"]
        assert "set-cookie" not in r.headers


def test_mutating_requests_require_csrf_header(client):
    assert client.post("/api/v1/auth/login", json={"username": "x", "password": "y"}).status_code == 403


def test_logout_and_tampered_tokens(client, make_user, settings):
    from api.sessions import issue_token

    uid = make_user("user4", ["VIEWER"])
    login(client, "user4")
    assert client.post("/api/v1/auth/logout", headers=H).status_code == 204
    assert client.get("/api/v1/auth/me").status_code == 401
    client.cookies.set(settings.api.cookie_name, issue_token(uid, "another-secret-" * 3, 30))
    assert client.get("/api/v1/auth/me").status_code == 401
    client.cookies.set(settings.api.cookie_name, issue_token(uid, client.app.state.session_secret, -1))
    assert client.get("/api/v1/auth/me").status_code == 401


def test_viewer_cannot_upload_or_change_settings(client, make_user):
    make_user("viewer", ["VIEWER"])
    login(client, "viewer")
    assert client.get("/api/v1/days").status_code == 200
    assert client.get("/api/v1/settings").status_code == 403
    assert client.put("/api/v1/settings/rules", json={}, headers=H).status_code == 403
    r = client.post("/api/v1/days/upload", files={"file": ("a.xlsx", b"x")}, headers=H)
    assert r.status_code == 403 and r.json() == {"detail": "Not authorised"}


def test_no_login_mode_acts_as_local_admin(open_client, settings):
    body = open_client.get("/api/v1/auth/me").json()
    assert body["auth_mode"] == "none" and body["username"] == settings.auth.default_user.username
    assert {p["slug"] for p in body["navigation"]} == {"upload", "insights", "mail", "emails", "reports", "employee-report", "employees", "settings"}
    assert open_client.post("/api/v1/auth/login", json={"username": "x", "password": "y"}, headers=H).status_code == 404


def test_security_headers(client):
    r = client.get("/api/health")
    assert r.headers["x-content-type-options"] == "nosniff"
    assert "frame-ancestors 'self'" in r.headers["content-security-policy"]
    assert r.headers["cache-control"] == "no-store"


def test_docs_disabled_in_production_like_settings(settings, engine, tmp_path):
    prod_like = settings.model_copy(update={"app": settings.app.model_copy(update={"environment": "production"})})
    with TestClient(create_app(prod_like, engine, frontend_dist=tmp_path)) as c:
        assert c.get("/api/docs").status_code == 404


def test_navigation_filtered_by_permission():
    viewer = Principal(1, "u", "U", permissions=frozenset({Perm.VIEW_INSIGHTS.value}))
    assert {p.slug for p in visible_pages(viewer)} == {"insights", "mail", "emails", "reports", "employee-report", "employees"}
    assert visible_pages(Principal(1, "u", "U")) == []
    assert len({p.slug for p in PAGES}) == len(PAGES) == 8


def test_spa_served_with_fallback_and_no_traversal(settings, engine, tmp_path):
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<html>APP</html>")
    (dist / "assets" / "app.js").write_text("console.log(1)")
    (tmp_path / "secret.txt").write_text("TOP SECRET")
    with TestClient(create_app(settings, engine, frontend_dist=dist)) as c:
        assert "APP" in c.get("/").text and "APP" in c.get("/insights").text
        assert c.get("/assets/app.js").status_code == 200
        assert "TOP SECRET" not in c.get("/..%2Fsecret.txt").text
        assert c.get("/api/v1/nope").status_code == 404
