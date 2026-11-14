from __future__ import annotations

from monitoring.health import Status, check_rules, check_storage, run_all


def test_storage_check_ok(settings):
    assert check_storage(settings).status is Status.OK


def test_rules_check_warns_while_unapproved():
    result = check_rules()
    assert result.status is Status.WARN and "PROVISIONAL" in result.detail


def test_full_health_on_migrated_sqlite(engine, settings):
    results = {r.name: r for r in run_all(settings, engine)}
    assert results["Configuration"].status is Status.OK
    db = results["Database"]
    assert db.status is Status.WARN and "SQLite development database" in db.detail
    assert not any(r.status is Status.FAIL for r in results.values())


def test_health_before_migration_warns(settings):
    from database.connection import create_db_engine

    results = {r.name: r for r in run_all(settings, create_db_engine(settings))}
    assert results["Database"].status is Status.WARN and "init-db" in results["Database"].detail


def test_cli_init_db_and_check(isolated_env, capsys):
    import main

    assert main.main(["init-db"]) == 0
    assert "Security model synced" in capsys.readouterr().out
    assert main.main(["check"]) == 0
    out = capsys.readouterr().out
    assert "[OK  ] Configuration" in out


def test_cli_create_user_rejects_weak_password(isolated_env, monkeypatch, capsys):
    import main

    main.main(["init-db"])
    monkeypatch.setattr("getpass.getpass", lambda prompt="": "weak")
    assert main.main(["create-user", "--username", "x", "--role", "READ_ONLY"]) == 2
    assert "Password rejected" in capsys.readouterr().out


def test_cli_create_user_hod_requires_department(isolated_env, capsys):
    import main

    assert main.main(["create-user", "--username", "h", "--role", "HOD"]) == 2
    assert "--department" in capsys.readouterr().out


def test_cli_create_user_success(isolated_env, monkeypatch, capsys):
    import main

    main.main(["init-db"])
    monkeypatch.setattr("getpass.getpass", lambda prompt="": "Strong-Passw0rd!")
    assert main.main(["create-user", "--username", "Admin.One", "--role", "SYSTEM_ADMIN"]) == 0
    assert "Created user 'admin.one'" in capsys.readouterr().out
