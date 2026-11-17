"""Command-line entry point for administrative tasks.

    python main.py check                 Validate config, storage and database
    python main.py init-db               Apply migrations and sync roles/permissions
    python main.py create-user ...       Create a local user (password prompted, never echoed)
    python main.py upload FILE           Process one day's file and email the reports
    python main.py serve                 Start the app (UI + API)
"""

from __future__ import annotations

import argparse
import getpass

from core.config import get_settings
from core.exceptions import AppError
from core.logging_setup import configure_logging
from core.paths import PROJECT_ROOT


def _engine():
    from database.connection import create_db_engine

    return create_db_engine(get_settings())


def cmd_check(_: argparse.Namespace) -> int:
    from monitoring.health import Status, run_all

    settings = get_settings()
    try:
        engine = _engine()
    except AppError as exc:
        print(f"Database configuration error: {exc}")
        engine = None
    results = run_all(settings, engine)
    width = max(len(r.name) for r in results)
    for r in results:
        print(f"[{r.status:<4}] {r.name:<{width}}  {r.detail}")
    return 1 if any(r.status is Status.FAIL for r in results) else 0


def cmd_init_db(_: argparse.Namespace) -> int:
    from database.connection import session_scope
    from database.migrate import upgrade_to_head
    from database.repositories.security_repository import SecurityRepository

    settings = get_settings()
    engine = _engine()
    upgrade_to_head(engine)
    with session_scope(engine) as session:
        counts = SecurityRepository(session).sync_roles_and_permissions(settings.security)
    print(f"Database ready. Access roles synced: {counts}")
    return 0


def cmd_create_user(args: argparse.Namespace) -> int:
    from database.connection import session_scope
    from database.repositories.security_repository import SecurityRepository
    from security.audit import record_activity
    from security.authentication import hash_password, validate_password_policy
    from security.permissions import Role

    settings = get_settings()
    roles = [r.upper() for r in (args.role or ["ADMIN"])]
    invalid = [r for r in roles if r not in Role.__members__]
    if invalid:
        print(f"Unknown role(s): {invalid}. Valid: {list(Role.__members__)}")
        return 2
    if "HOD" in roles and not args.department:
        print("HOD users need at least one --department.")
        return 2

    import os

    if args.password_env:
        password = os.environ.get(args.password_env, "")
        if not password:
            print(f"Environment variable {args.password_env} is empty.")
            return 2
    else:
        password = getpass.getpass("Password: ")
    problems = validate_password_policy(password, settings.session.min_password_length)
    if problems and not args.allow_weak_password:
        print("Password rejected: " + "; ".join(problems))
        return 2
    if problems:
        print("WARNING: weak password accepted on request (" + "; ".join(problems) + ").")
    if not args.password_env and getpass.getpass("Confirm password: ") != password:
        print("Passwords do not match.")
        return 2

    with session_scope(_engine()) as session:
        repo = SecurityRepository(session)
        user = repo.create_user(
            username=args.username,
            display_name=args.display_name or args.username,
            password_hash=hash_password(password),
            roles=roles,
            departments=args.department,
            email=args.email,
            created_by=f"cli:{getpass.getuser()}",
        )
        record_activity(
            session, "USER_CREATE", "SUCCESS", user_id=user.user_id, username=user.username,
            detail={"roles": roles, "departments": args.department or [], "via": "cli"},
        )
        print(f"Created user {user.username!r} (id {user.user_id}) with roles {roles}")
    return 0


def cmd_serve(args: argparse.Namespace) -> int:
    import uvicorn

    from core.config import LOOPBACK_HOSTS

    settings = get_settings()
    api = settings.api
    host = args.host or api.host
    if settings.auth.mode == "none" and host not in LOOPBACK_HOSTS:
        print("Refusing to start: auth.mode 'none' (no login) may only listen on localhost. "
              "Use auth.mode 'local' (or AUTH_MODE=local) to serve other machines.")
        return 2
    if settings.auth.mode == "none":
        print("No-login mode: every request acts as the configured local operator (localhost only).")
    uvicorn.run(
        "api.main:create_app", factory=True,
        host=host, port=args.port or api.port,
        reload=args.reload, reload_dirs=[str(PROJECT_ROOT)] if args.reload else None,
        log_config=None,  # keep the application's structured logging
    )
    return 0


def _upload(paths, replace: bool, mode: str | None = None, master=None) -> int:
    from daily import mail
    from daily.analysis import FileError
    from daily.service import AlreadyUploaded, upload_files_and_send
    from database.connection import session_scope

    settings = get_settings()
    actor = f"cli:{getpass.getuser()}"
    try:
        with session_scope(_engine()) as session:
            if master is not None:
                from daily import employees as emp
                from daily import routing

                data = master.read_bytes()
                res = emp.import_rows(session, emp.read_master_file(master.name, data), actor)
                extras = emp.read_routing_extras(master.name, data)
                if extras:
                    routing.apply_workbook(session, settings, extras, actor)
                print(f"Employee master: {res.added} added, {res.updated} updated, {res.unchanged} unchanged.")
                if not paths:
                    return 0
            upload, items, note = upload_files_and_send(session, settings, [(p.name, p.read_bytes()) for p in paths],
                                                        actor, replace=replace, mode=mode)
            print(f"{upload.report_date:%d-%b-%Y}: {upload.employees} employees processed.")
            for i in items:
                print(f"  email {i.recipient_name} <{i.to_addrs or '-'}>: {i.status} {i.note or ''}".rstrip())
            if note:
                print(f"  {note}")
            failed = any(i.status == mail.FAILED for i in items)
    except (FileError, AlreadyUploaded) as exc:
        print(f"Not processed: {exc}")
        return 3
    except Exception as exc:  # employee master problems
        from daily.employees import EmployeeError

        if not isinstance(exc, EmployeeError):
            raise
        print(f"Employee master not imported: {exc}")
        return 3
    return 1 if failed else 0


def cmd_upload(args: argparse.Namespace) -> int:
    """Upload one day's Pocket HRMS Attendance Summary and/or Permission Report from the command
    line (for scheduling). Emails are prepared and - unless approval is required - sent."""
    from pathlib import Path

    paths = [Path(f) for f in args.files]
    master = Path(args.master) if args.master else None
    missing = [p for p in paths + ([master] if master else []) if not p.is_file()]
    if missing:
        print(f"File not found: {missing[0]}")
        return 2
    if not paths and master is None:
        print("Give at least one file.")
        return 2
    return _upload(paths, args.replace, args.send, master)


def cmd_watch(args: argparse.Namespace) -> int:
    """Watch a folder: each new .xlsx/.csv dropped there is uploaded like the Upload page does, then moved to
    'processed' (or 'failed' with a .txt note). Stop with Ctrl+C."""
    import contextlib
    import io
    import shutil
    import time
    from pathlib import Path

    folder = Path(args.folder)
    if not folder.is_dir():
        print(f"Folder not found: {folder}")
        return 2
    done, failed = folder / "processed", folder / "failed"
    done.mkdir(exist_ok=True)
    failed.mkdir(exist_ok=True)
    sizes: dict[Path, int] = {}
    print(f"Watching {folder} every {args.interval}s for Pocket HRMS files (Ctrl+C to stop).")
    while True:
        for f in sorted(folder.iterdir()):
            if not f.is_file() or f.suffix.lower() not in (".xlsx", ".csv") or f.name.startswith("~$"):
                continue
            stat = f.stat()
            settled = time.time() - stat.st_mtime >= 10
            if sizes.get(f) != stat.st_size and not settled:   # may still be being written
                sizes[f] = stat.st_size
                continue
            sizes.pop(f, None)
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                code = _upload([f], replace=False)
            print(out.getvalue().rstrip())
            target = (done if code in (0, 1) else failed) / f.name
            shutil.move(str(f), target)
            if code not in (0, 1):
                target.with_suffix(target.suffix + ".txt").write_text(out.getvalue(), encoding="utf-8")
        if args.once:
            return 0
        time.sleep(args.interval)


def cmd_gmail_auth(args: argparse.Namespace) -> int:
    """Connect the Gmail API once: sign in as the sender mailbox; the refresh token goes into .env."""
    import os
    import secrets as _secrets
    import webbrowser
    from pathlib import Path

    from daily import gmail_auth as ga

    env_path = PROJECT_ROOT / ".env"
    try:
        client = ga.client_from(dict(os.environ), Path(args.client_json) if args.client_json else None)
    except ga.GmailAuthError as exc:
        print(exc)
        return 2
    redirect = f"http://localhost:{args.port}/oauth2callback"
    state = _secrets.token_urlsafe(24)
    verifier, challenge = ga.pkce()
    url = ga.auth_url(client, redirect, state, challenge, args.login_hint)
    print("1. Sign in with the SENDER mailbox (the one the daily emails come from) and allow 'Send email on your behalf'.")
    print(f"   If Google says redirect_uri_mismatch: add {redirect} under Authorized redirect URIs of the OAuth client.")
    print("2. If the browser does not open, paste this address into it:")
    print(f"   {url}")
    if not args.no_browser:
        webbrowser.open(url)
    try:
        code = ga.wait_for_code(args.port, state, timeout=args.timeout)
        refresh, mailbox = ga.exchange(client, code, redirect, verifier)
    except ga.GmailAuthError as exc:
        print(f"Not connected: {exc}")
        return 3
    if args.client_json:
        ga.set_env_value(env_path, "GMAIL_CLIENT_ID", client.client_id)
        ga.set_env_value(env_path, "GMAIL_CLIENT_SECRET", client.client_secret)
    ga.set_env_value(env_path, "GMAIL_REFRESH_TOKEN", refresh)
    print(f"Gmail connected{f' as {mailbox}' if mailbox else ''}. The refresh token is saved in {env_path} (not shown, never committed).")
    if mailbox:
        from daily.settings_store import get_email_settings, save_email_settings
        from database.connection import session_scope

        settings = get_settings()
        with session_scope(_engine()) as session:
            cfg = get_email_settings(session, settings)
            save_email_settings(session, cfg.model_copy(update={"sender": mailbox}), "cli:gmail-auth")
        print(f"Settings: sender = {mailbox}. Restart the app so it reads the new token.")
    return 0


def _date_arg(value: str | None):
    from datetime import date

    return date.fromisoformat(value) if value else None


def cmd_run_daily(args: argparse.Namespace) -> int:
    """The 09:30 job (Windows Task Scheduler): yesterday's files from the inbox -> analyse -> verify -> send.
    Exit 0 = success, 1 = some emails failed (retry later), 3 = failed (alert sent), 4 = already running."""
    from pathlib import Path

    from daily import jobs

    try:
        r = jobs.run_daily(get_settings(), _engine(), _date_arg(args.date), Path(args.inbox) if args.inbox else None,
                           args.send, trigger="CLI" if args.manual else "SCHEDULED", actor=f"cli:{getpass.getuser()}")
    except jobs.JobLocked as exc:
        print(exc)
        return 4
    except Exception as exc:
        print(f"Daily job failed: {type(exc).__name__}: {exc}")
        return 3
    print(f"Daily job {r['date']}: {r['status']} | processed {r.get('processed', [])} | emails {r.get('emails', {})}"
          + (f" | {r['problem']}" if r.get("problem") else ""))
    return {"SUCCESS": 0, "PARTIAL": 1}.get(r["status"], 3)


def cmd_backup(args: argparse.Namespace) -> int:
    from daily import jobs

    try:
        r = jobs.backup(get_settings(), _engine(), trigger="CLI" if args.manual else "SCHEDULED", actor=f"cli:{getpass.getuser()}")
    except jobs.JobLocked as exc:
        print(exc)
        return 4
    except Exception as exc:
        print(f"Backup failed: {type(exc).__name__}: {exc}")
        return 3
    print(f"Backup OK: {r['file']} ({r['bytes']:,} bytes, integrity {r['integrity']}, {r['pruned']} old copies removed)")
    return 0


def cmd_monthly(args: argparse.Namespace) -> int:
    from daily import jobs, monthly

    try:
        r = monthly.generate(get_settings(), _engine(), args.month, args.send, trigger="CLI" if args.manual else "SCHEDULED",
                             actor=f"cli:{getpass.getuser()}")
    except jobs.JobLocked as exc:
        print(exc)
        return 4
    print(f"Monthly {r['month']}: {r['status']} | days {r.get('days')} | employees {r.get('employees')} | "
          f"attendance {r.get('attendance_pct')}% | emails {r.get('emails')}" + (f" | {r['problem']}" if r.get("problem") else ""))
    return {"SUCCESS": 0, "PARTIAL": 1}.get(r["status"], 3)


def cmd_cleanup(args: argparse.Namespace) -> int:
    from daily import jobs, monthly

    try:
        r = monthly.cleanup(get_settings(), _engine(), args.month, args.confirm, trigger="CLI", actor=f"cli:{getpass.getuser()}")
    except jobs.JobLocked as exc:
        print(exc)
        return 4
    if r["status"] == "BLOCKED":
        print(f"Cleanup of {args.month} NOT allowed:")
        for p in r["problems"]:
            print(f"  - {p}")
        return 3
    if r["status"] == "PREVIEW":
        print(f"Cleanup of {args.month} is allowed: {r['days']} day(s) of daily rows and stored files would be removed. "
              f"Run again with --confirm to do it.")
        return 0
    print(f"Cleanup of {args.month} done: {r['rows_deleted']} daily rows deleted, {r['upload_folders_removed']} upload folders removed.")
    return 0


def cmd_demo(args: argparse.Namespace) -> int:
    from demo.builder import DEMO_DB, build

    print(f"Building SYNTHETIC demo data ({args.days} days) in {DEMO_DB.parent} ...")
    build(get_settings(), days=args.days)
    print("Done. Start the demo with:  python main.py serve --demo")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="main.py", description="APIS Attendance MIS administration")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("check", help="validate configuration, storage and database").set_defaults(func=cmd_check)
    sub.add_parser("init-db", help="apply migrations and sync roles/permissions").set_defaults(func=cmd_init_db)

    cu = sub.add_parser("create-user", help="create a local user")
    cu.add_argument("--username", required=True)
    cu.add_argument("--display-name")
    cu.add_argument("--email")
    cu.add_argument("--role", action="append", help="default ADMIN - the application has one user (HR) who does everything")
    cu.add_argument("--department", action="append", help="department code scope (repeatable)")
    cu.add_argument("--password-env", help="read the password from this environment variable instead of prompting")
    cu.add_argument("--allow-weak-password", action="store_true",
                    help="accept a password that fails the password policy (the owner's explicit choice; shown as a warning)")
    cu.set_defaults(func=cmd_create_user)

    serve = sub.add_parser("serve", help="start the API server (serves frontend/dist when built)")
    serve.add_argument("--host")
    serve.add_argument("--port", type=int)
    serve.add_argument("--reload", action="store_true", help="development auto-reload")
    serve.add_argument("--demo", action="store_true", help="use the synthetic demo database (storage/demo)")
    serve.set_defaults(func=cmd_serve)

    up = sub.add_parser("upload", help="process one day's Pocket HRMS Attendance Summary and/or Permission Report and email the reports")
    up.add_argument("files", nargs="*", help="Pocket HRMS AttendanceSummary and/or PermissionReport (.xlsx/.csv)")
    up.add_argument("--master", help="employee master / routing workbook to import first (optional)")
    up.add_argument("--send", choices=["auto", "manual"], help="auto = send the emails now; manual = wait for approval "
                                                                "(default: Settings)")
    up.add_argument("--replace", action="store_true", help="replace an existing upload for the same date")
    up.set_defaults(func=cmd_upload)

    g = sub.add_parser("gmail-auth", help="connect the Gmail API once (sign in as the sender mailbox)")
    g.add_argument("--port", type=int, default=8765, help="local port for Google's redirect (default 8765)")
    g.add_argument("--client-json", help="OAuth client JSON downloaded from Google Cloud (instead of .env values)")
    g.add_argument("--login-hint", help="sender mailbox address, pre-filled on Google's sign-in page")
    g.add_argument("--no-browser", action="store_true", help="only print the sign-in address")
    g.add_argument("--timeout", type=int, default=600, help="seconds to wait for the sign-in (default 600)")
    g.set_defaults(func=cmd_gmail_auth)

    rd = sub.add_parser("run-daily", help="the 09:30 job: yesterday's files from the inbox -> emails (Task Scheduler)")
    rd.add_argument("--date", help="report date YYYY-MM-DD (default: yesterday, IST)")
    rd.add_argument("--inbox", help="folder with the day's Pocket HRMS files (default: jobs.inbox_dir)")
    rd.add_argument("--send", choices=["auto", "manual"], help="default: Settings (preview mode -> manual)")
    rd.add_argument("--manual", action="store_true", help="record as a manual run instead of SCHEDULED")
    rd.set_defaults(func=cmd_run_daily)

    bk = sub.add_parser("backup", help="online backup of the SQLite database (integrity-checked; old copies pruned)")
    bk.add_argument("--manual", action="store_true")
    bk.set_defaults(func=cmd_backup)

    mo = sub.add_parser("monthly", help="month-end reports + archive (default: previous month)")
    mo.add_argument("--month", help="YYYY-MM (default: previous month)")
    mo.add_argument("--send", choices=["auto", "manual"])
    mo.add_argument("--manual", action="store_true")
    mo.set_defaults(func=cmd_monthly)

    cl = sub.add_parser("cleanup", help="remove a month's daily rows after its archive and a later backup are verified")
    cl.add_argument("--month", required=True, help="YYYY-MM")
    cl.add_argument("--confirm", action="store_true", help="actually delete (without it: only check and preview)")
    cl.set_defaults(func=cmd_cleanup)

    w = sub.add_parser("watch", help="watch a folder and process each attendance file dropped there")
    w.add_argument("folder")
    w.add_argument("--interval", type=int, default=30, help="seconds between checks (default 30)")
    w.add_argument("--once", action="store_true", help="check once and exit (for Task Scheduler)")
    w.set_defaults(func=cmd_watch)

    demo = sub.add_parser("demo", help="build a SYNTHETIC demo database in storage/demo (never touches real data)")
    demo.add_argument("--days", type=int, default=10)
    demo.set_defaults(func=cmd_demo, demo=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if getattr(args, "demo", False):
        import os

        from demo.builder import demo_env

        os.environ.update(demo_env())       # must happen before settings are first loaded
        get_settings.cache_clear()
    try:
        configure_logging(get_settings())
        return args.func(args)
    except AppError as exc:
        print(f"Error: {exc}")
        return 1
    except ValueError as exc:
        print(f"Error: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
