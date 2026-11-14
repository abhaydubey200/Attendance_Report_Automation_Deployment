"""REST API tests via FastAPI's TestClient (in-process, no network)."""

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
    """Sign-in (auth.mode 'local') client -- exercises the full authentication path."""
    app = create_app(with_auth_mode(settings, "local"), engine, frontend_dist=tmp_path / "no-dist")
    with TestClient(app) as c:
        yield c


@pytest.fixture
def open_client(settings, engine, tmp_path):
    """No-login client (auth.mode 'none', the shipped development default)."""
    assert settings.auth.mode == "none"
    with TestClient(create_app(settings, engine, frontend_dist=tmp_path / "no-dist")) as c:
        yield c


def login(client: TestClient, username: str, password: str = TEST_PASSWORD):
    return client.post("/api/v1/auth/login", json={"username": username, "password": password}, headers=H)


# --------------------------------------------------------------------------- auth
def test_liveness_is_public_and_minimal(client):
    r = client.get("/api/health")
    assert r.status_code == 200 and r.json() == {"status": "ok"}


def test_protected_endpoints_require_login(client):
    for path in ("/api/v1/auth/me", "/api/v1/dashboard/summary", "/api/v1/system/health", "/api/v1/admin/users"):
        assert client.get(path).status_code == 401, path


def test_login_sets_httponly_cookie_and_returns_profile(client, make_user, settings):
    make_user("hr.manager", ["HR_MANAGER"])
    r = login(client, "HR.Manager")
    assert r.status_code == 200
    body = r.json()
    assert body["username"] == "hr.manager" and "HR_MANAGER" in body["roles"]
    assert "dashboard" in {p["slug"] for p in body["navigation"]}
    cookie = r.headers["set-cookie"].lower()
    assert settings.api.cookie_name in cookie and "httponly" in cookie and "samesite=strict" in cookie
    assert client.get("/api/v1/auth/me").status_code == 200


def test_bad_login_is_generic_and_sets_no_cookie(client, make_user):
    make_user("user1", ["READ_ONLY"])
    for username in ("user1", "nobody"):
        r = login(client, username, "wrong")
        assert r.status_code == 401 and "Invalid username or password" in r.json()["detail"]
        assert "set-cookie" not in r.headers


def test_failed_logins_persist_and_lock_account(client, make_user, settings):
    make_user("user2", ["READ_ONLY"])
    for _ in range(settings.session.max_failed_logins):
        assert login(client, "user2", "wrong").status_code == 401
    assert login(client, "user2").status_code == 401   # locked even with the right password


def test_mutating_requests_require_csrf_header(client, make_user):
    make_user("user3", ["READ_ONLY"])
    r = client.post("/api/v1/auth/login", json={"username": "user3", "password": TEST_PASSWORD})
    assert r.status_code == 403


def test_logout_clears_session(client, make_user):
    make_user("user4", ["READ_ONLY"])
    login(client, "user4")
    r = client.post("/api/v1/auth/logout", headers=H)
    assert r.status_code == 204
    assert client.get("/api/v1/auth/me").status_code == 401


def test_tampered_or_foreign_token_rejected(client, make_user, settings):
    from api.sessions import issue_token

    uid = make_user("user5", ["READ_ONLY"])
    client.cookies.set(settings.api.cookie_name, issue_token(uid, "some-other-secret-" * 3, 30))
    assert client.get("/api/v1/auth/me").status_code == 401
    client.cookies.set(settings.api.cookie_name, "not-a-jwt")
    assert client.get("/api/v1/auth/me").status_code == 401


def test_expired_token_rejected(client, make_user, settings):
    from api.sessions import issue_token

    uid = make_user("user6", ["READ_ONLY"])
    client.cookies.set(settings.api.cookie_name, issue_token(uid, client.app.state.session_secret, -1))
    assert client.get("/api/v1/auth/me").status_code == 401


def test_deactivated_user_loses_access_immediately(client, make_user, engine):
    from database.connection import session_scope
    from database.repositories.security_repository import SecurityRepository

    uid = make_user("leaver", ["HR_ADMIN"])
    login(client, "leaver")
    with session_scope(engine) as s:
        SecurityRepository(s).get_user(uid).is_active = False
    assert client.get("/api/v1/auth/me").status_code == 401


# --------------------------------------------------------------------------- authorization
def test_hod_cannot_reach_admin_or_system(client, make_user):
    make_user("hod", ["HOD"], departments=["SALES"])
    login(client, "hod")
    assert client.get("/api/v1/dashboard/summary").status_code == 200
    for path in ("/api/v1/admin/users", "/api/v1/system/health", "/api/v1/system/config"):
        r = client.get(path)
        assert r.status_code == 403 and r.json() == {"detail": "Not authorised"}, path


def test_system_admin_has_no_dashboard(client, make_user):
    make_user("sys", ["SYSTEM_ADMIN"])
    login(client, "sys")
    assert client.get("/api/v1/dashboard/summary").status_code == 403
    assert client.get("/api/v1/system/health").status_code == 200
    users = client.get("/api/v1/admin/users").json()
    assert [u["username"] for u in users] == ["sys"]
    assert "password_hash" not in users[0]


# --------------------------------------------------------------------------- content
def test_dashboard_is_empty_and_rules_unapproved(client, make_user):
    make_user("dir", ["DIRECTOR"])
    login(client, "dir")
    body = client.get("/api/v1/dashboard/summary").json()
    assert body["rules_approved"] is False and body["rule_approval_status"] == "NOT_APPROVED"
    assert body["run"] is None and "No processed attendance" in body["message"]


def test_system_config_never_exposes_secrets(client, make_user):
    make_user("sys2", ["SYSTEM_ADMIN"])
    login(client, "sys2")
    r = client.get("/api/v1/system/config")
    assert r.status_code == 200
    text = r.text.lower()
    assert "password" not in text and "secret" not in text
    assert len(r.json()["datasets"]) == 8


def test_security_headers(client):
    r = client.get("/api/health")
    assert r.headers["x-content-type-options"] == "nosniff"
    assert "frame-ancestors 'self'" in r.headers["content-security-policy"]
    assert r.headers["cache-control"] == "no-store"


def test_docs_disabled_in_production_like_settings(settings, engine, tmp_path):
    prod_like = settings.model_copy(update={"app": settings.app.model_copy(update={"environment": "production"})})
    with TestClient(create_app(prod_like, engine, frontend_dist=tmp_path)) as c:
        assert c.get("/api/docs").status_code == 404


# --------------------------------------------------------------------------- navigation + SPA
def _p(*perms: Perm) -> Principal:
    return Principal(1, "u", "U", permissions=frozenset(p.value for p in perms))


def test_navigation_is_permission_filtered():
    hod = {p.slug for p in visible_pages(_p(Perm.DASHBOARD_VIEW, Perm.REPORT_VIEW_HOD))}
    assert "hod-reports" in hod and "directors-reports" not in hod and "users" not in hod
    assert visible_pages(_p()) == []


def test_page_registry_is_consistent():
    slugs = [p.slug for p in PAGES]
    assert len(slugs) == len(set(slugs))
    assert all(p.implemented for p in PAGES)


def test_spa_served_with_fallback_and_no_traversal(settings, engine, tmp_path):
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<html>APP</html>")
    (dist / "assets" / "app.js").write_text("console.log(1)")
    (tmp_path / "secret.txt").write_text("TOP SECRET")
    with TestClient(create_app(settings, engine, frontend_dist=dist)) as c:
        assert "APP" in c.get("/").text
        assert "APP" in c.get("/system-health").text          # client-side route
        assert c.get("/assets/app.js").status_code == 200
        assert "TOP SECRET" not in c.get("/..%2Fsecret.txt").text
        assert c.get("/api/v1/nope").status_code == 404


# --------------------------------------------------------------------------- no-login mode
def test_no_login_mode_acts_as_local_operator(open_client, settings):
    r = open_client.get("/api/v1/auth/me")
    assert r.status_code == 200
    body = r.json()
    assert body["auth_mode"] == "none"
    assert body["username"] == settings.auth.default_user.username
    assert set(body["roles"]) == set(settings.auth.default_user.roles)
    # Permissions come from the central role store, not from the client.
    assert "DASHBOARD_VIEW" in body["permissions"] and "ADMIN_USERS" in body["permissions"]
    assert "set-cookie" not in r.headers
    for path in ("/api/v1/dashboard/summary", "/api/v1/system/health", "/api/v1/admin/users"):
        assert open_client.get(path).status_code == 200, path


def test_no_login_mode_disables_login_endpoint(open_client):
    r = open_client.post("/api/v1/auth/login", json={"username": "x", "password": "y"}, headers=H)
    assert r.status_code == 404


def test_no_login_mode_still_enforces_role_permissions(settings, engine, tmp_path):
    """A narrower default user only gets that role's pages and endpoints."""
    narrow = settings.model_copy(update={"auth": settings.auth.model_copy(update={
        "default_user": settings.auth.default_user.model_copy(update={"roles": ("DIRECTOR",)})})})
    with TestClient(create_app(narrow, engine, frontend_dist=tmp_path)) as c:
        assert c.get("/api/v1/dashboard/summary").status_code == 200
        assert c.get("/api/v1/admin/users").status_code == 403
        assert "users" not in {p["slug"] for p in c.get("/api/v1/auth/me").json()["navigation"]}


def test_no_login_mode_still_requires_csrf_header_for_writes(open_client):
    assert open_client.post("/api/v1/auth/logout").status_code == 403
