from __future__ import annotations

import pytest

from core.config import DatabaseProfile
from core.exceptions import DatabaseConfigurationError
from database.connection import build_url

MSSQL = DatabaseProfile(name="mssql", backend="mssql", driver="ODBC Driver 18 for SQL Server", port=1433)


def test_mssql_requires_host_and_name():
    with pytest.raises(DatabaseConfigurationError, match="DB_HOST"):
        build_url(MSSQL, env={})


def test_mssql_requires_credentials_or_trusted_connection():
    with pytest.raises(DatabaseConfigurationError, match="DB_USER"):
        build_url(MSSQL, env={"DB_HOST": "h", "DB_NAME": "d"})


def test_mssql_sql_auth_url():
    url = build_url(MSSQL, env={"DB_HOST": "srv", "DB_NAME": "mis", "DB_USER": "u", "DB_PASSWORD": "p@ss;word"})
    assert url.drivername == "mssql+pyodbc"
    assert url.host == "srv" and url.port == 1433 and url.database == "mis"
    assert url.query["Encrypt"] == "yes" and url.query["TrustServerCertificate"] == "no"
    # Password never appears in the rendered (loggable) form.
    assert "p@ss;word" not in url.render_as_string(hide_password=True)


def test_mssql_trusted_connection_url():
    url = build_url(MSSQL, env={"DB_HOST": "srv", "DB_NAME": "mis", "DB_TRUSTED_CONNECTION": "yes", "DB_PORT": "1500"})
    assert url.query["Trusted_Connection"] == "yes"
    assert url.username is None and url.port == 1500
