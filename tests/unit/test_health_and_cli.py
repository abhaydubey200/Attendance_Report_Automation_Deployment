from __future__ import annotations

from datetime import date

from demo.synthetic import build_summary_xlsx
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
    assert main.main(["upload", str(f)]) == 0
    out = capsys.readouterr().out
    assert "13-Nov-2026: 42 employees processed." in out and "NO_RECIPIENTS" in out
    assert main.main(["upload", str(f)]) == 3                       # same date again without --replace
    assert "already uploaded" in capsys.readouterr().out
    assert main.main(["upload", str(f), "--replace"]) == 0
