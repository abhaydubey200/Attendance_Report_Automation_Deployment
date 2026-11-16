"""Database screen: read-only browsing of every table, secrets masked, names validated."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from api.main import CSRF_HEADER, create_app
from database.connection import session_scope
from database.models.daily import Employee
from security.authentication import hash_password


@pytest.fixture
def api(settings, engine, tmp_path):
    with session_scope(engine) as s:
        for i in range(1, 8):
            s.add(Employee(code=f"E{i}", name=f"Person {i}", department="Finance" if i % 2 else "Sales", status="ACTIVE"))
    with TestClient(create_app(settings, engine, frontend_dist=tmp_path / "no-dist")) as c:
        yield c


def test_lists_tables_with_counts(api):
    r = api.get("/api/v1/db/tables")
    assert r.status_code == 200
    by = {t["name"]: t for t in r.json()["tables"]}
    assert by["employee"]["rows"] == 7 and "Employee master" in by["employee"]["description"]
    assert {"employee_day", "mail_item", "app_setting", "app_user"} <= set(by)


def test_browse_search_sort_and_page(api):
    r = api.get("/api/v1/db/tables/employee", params={"limit": 3, "offset": 0, "sort": "code", "direction": "asc"}).json()
    names = [c["name"] for c in r["columns"]]
    assert r["total"] == 7 and len(r["rows"]) == 3 and r["rows"][0][names.index("code")] == "E1"
    r = api.get("/api/v1/db/tables/employee", params={"q": "sales"}).json()
    assert r["total"] == 3
    page2 = api.get("/api/v1/db/tables/employee", params={"limit": 5, "offset": 5, "sort": "code"}).json()
    assert [row[names.index("code")] for row in page2["rows"]] == ["E6", "E7"]
    csv = api.get("/api/v1/db/tables/employee/csv", params={"q": "finance"})
    assert csv.status_code == 200 and csv.text.count("\n") == 1 + 4 and "attachment" in csv.headers["content-disposition"]


def test_rejects_unknown_tables_and_columns(api):
    assert api.get("/api/v1/db/tables/not_a_table").status_code == 404
    assert api.get("/api/v1/db/tables/employee; drop table employee").status_code == 404
    assert api.get("/api/v1/db/tables/employee", params={"sort": "code; drop table employee"}).status_code == 422
    assert api.get("/api/v1/db/tables").json()["tables"]          # still there


def test_secret_columns_are_masked(api, engine):
    from database.models.security import AppUser
    with session_scope(engine) as s:
        s.add(AppUser(username="hr", display_name="HR", password_hash=hash_password("Sup3r-secret-pass!"), auth_provider="LOCAL"))
    r = api.get("/api/v1/db/tables/app_user").json()
    col = [c["name"] for c in r["columns"]].index("password_hash")
    assert r["columns"][col]["hidden"] and r["rows"][0][col] == "•••••• (hidden)"
    assert "$2" not in api.get("/api/v1/db/tables/app_user/csv").text.lower()
    assert api.get("/api/v1/db/tables/app_user", params={"q": "$2"}).json()["total"] == 0   # hashes are not searchable


def test_read_only_no_write_methods(api):
    for method in ("post", "put", "patch", "delete"):
        assert getattr(api, method)("/api/v1/db/tables/employee", headers={CSRF_HEADER: "1"}).status_code == 405
