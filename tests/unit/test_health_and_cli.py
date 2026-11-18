from __future__ import annotations

from datetime import date

from demo.synthetic import build_permission_xlsx, build_summary_xlsx
from monitoring.health import Status, check_storage, run_all


def test_storage_check_ok(settings):
    assert check_storage(settings).status is Status.OK


def test_health_before_and_after_init(isolated_env, settings):
    import main
    from database.connection import create_db_engine

    results = {r.name: r for r in run_all(settings, create_db_engine(settings))}
    assert results["Database"].status is Status.WARN and "init-db" in results["Database"].detail
    assert main.main(["init-db"]) == 0
    results = {r.name: r for r in run_all(settings, create_db_engine(settings))}
    assert results["Database"].status is Status.OK
    assert results["Email"].status is Status.WARN and "test mode" in results["Email"].detail


def test_cli_check(isolated_env, capsys):
    import main

    main.main(["init-db"])
    assert main.main(["check"]) == 0
    assert "[OK  ] Configuration" in capsys.readouterr().out


def test_cli_create_user(isolated_env, monkeypatch, capsys):
    import main

    main.main(["init-db"])
    monkeypatch.setattr("getpass.getpass", lambda prompt="": "weak")
    assert main.main(["create-user", "--username", "x", "--role", "VIEWER"]) == 2
    monkeypatch.setattr("getpass.getpass", lambda prompt="": "Strong-Passw0rd!")
    assert main.main(["create-user", "--username", "Admin.One", "--role", "ADMIN"]) == 0
    assert "Created user 'admin.one'" in capsys.readouterr().out


def test_cli_upload_processes_and_saves_emails(isolated_env, tmp_path, capsys):
    import main

    main.main(["init-db"])
    f = tmp_path / "AttendanceSummary.xlsx"
    f.write_bytes(build_summary_xlsx(date(2026, 11, 13)))
    b = tmp_path / "PermissionReport.xlsx"
    b.write_bytes(build_permission_xlsx(date(2026, 11, 13)))
    assert main.main(["upload", str(f)]) == 0
    out = capsys.readouterr().out
    assert "13-Nov-2026: 42 employees processed." in out and "Waiting for the Permission Report" in out
    assert main.main(["upload", str(b)]) == 0                       # second file merges and triggers the emails
    out = capsys.readouterr().out
    assert "42 employees processed" in out and "Director email not set" in out   # emails prepared, held until set up
    assert main.main(["upload", str(f)]) == 3                       # same date again without --replace
    assert "already uploaded" in capsys.readouterr().out
    assert main.main(["upload", str(f), "--replace"]) == 0


def test_cli_upload_three_datasets_auto(isolated_env, tmp_path, capsys):
    import main
    from demo.synthetic import build_master_xlsx

    main.main(["init-db"])
    m, f, b = tmp_path / "master.xlsx", tmp_path / "AttendanceSummary.xlsx", tmp_path / "PermissionReport.xlsx"
    m.write_bytes(build_master_xlsx())
    f.write_bytes(build_summary_xlsx(date(2026, 11, 13)))
    b.write_bytes(build_permission_xlsx(date(2026, 11, 13)))
    assert main.main(["upload", "--master", str(m), str(f), str(b), "--send", "auto"]) == 0
    out = capsys.readouterr().out
    assert "Employee master: 41 added" in out and ": SAVED" in out and "ready - review" not in out


def test_cli_password_reset_unlock_and_list(isolated_env, monkeypatch, capsys):
    import main
    from datetime import timedelta

    from core.timeutils import now_utc
    from database.connection import create_db_engine, session_scope
    from database.repositories.security_repository import SecurityRepository
    from core.config import get_settings

    main.main(["init-db"])
    monkeypatch.setenv("PW", "root")
    assert main.main(["create-user", "--username", "root", "--password-env", "PW"]) == 2          # weak: refused by default
    assert main.main(["create-user", "--username", "root", "--password-env", "PW", "--allow-weak-password"]) == 0
    assert "WARNING: weak password" in capsys.readouterr().out
    with session_scope(create_db_engine(get_settings())) as s:
        SecurityRepository(s).get_user_by_username("root").locked_until = now_utc() + timedelta(minutes=15)
    assert main.main(["list-users"]) == 0 and "LOCKED" in capsys.readouterr().out
    assert main.main(["unlock-user", "--username", "root"]) == 0 and "unlocked" in capsys.readouterr().out
    assert main.main(["list-users"]) == 0 and "LOCKED" not in capsys.readouterr().out
    monkeypatch.setenv("PW", "New-Passw0rd!x")
    assert main.main(["set-password", "--username", "root", "--password-env", "PW"]) == 0
    assert main.main(["unlock-user", "--username", "nobody"]) == 2


def test_cli_backup_and_restore(isolated_env, capsys):
    import sqlite3

    import main
    from core.config import get_settings

    main.main(["init-db"])
    assert main.main(["backup", "--manual"]) == 0
    db = get_settings().database.path
    con = sqlite3.connect(db)
    con.execute("delete from app_role")
    con.commit()
    assert con.execute("select count(*) from app_role").fetchone()[0] == 0
    con.close()
    assert main.main(["restore"]) == 0 and "Dry run only" in capsys.readouterr().out
    holder = sqlite3.connect(db)                       # still in use -> refused
    holder.execute("select 1").fetchone()
    assert main.main(["restore", "--yes"]) == 4
    holder.close()
    import gc

    from sqlalchemy.engine import Engine
    for o in gc.get_objects():                         # close this test process's pooled connections (the server's
        if isinstance(o, Engine):                      # app and jobs are stopped before a real restore)
            o.dispose()
    assert main.main(["restore", "--yes"]) == 0 and "Restored." in capsys.readouterr().out
    con = sqlite3.connect(db)
    assert con.execute("select count(*) from app_role").fetchone()[0] > 0
    con.close()
