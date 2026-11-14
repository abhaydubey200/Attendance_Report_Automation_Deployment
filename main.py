"""Command-line entry point for administrative tasks.

    python main.py check                 Validate config, storage and database
    python main.py init-db               Apply migrations and sync roles/permissions
    python main.py create-user ...       Create a local user (password prompted, never echoed)
    python main.py serve                 Start the API (+ built React UI) with uvicorn
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
    print(f"Migrations applied. Security model synced: {counts}")
    return 0


def cmd_create_user(args: argparse.Namespace) -> int:
    from database.connection import session_scope
    from database.repositories.security_repository import SecurityRepository
    from security.audit import record_activity
    from security.authentication import hash_password, validate_password_policy
    from security.permissions import Role

    settings = get_settings()
    roles = [r.upper() for r in args.role]
    invalid = [r for r in roles if r not in Role.__members__]
    if invalid:
        print(f"Unknown role(s): {invalid}. Valid: {list(Role.__members__)}")
        return 2
    if "HOD" in roles and not args.department:
        print("HOD users need at least one --department.")
        return 2

    password = getpass.getpass("Password: ")
    problems = validate_password_policy(password, settings.session.min_password_length)
    if problems:
        print("Password rejected: " + "; ".join(problems))
        return 2
    if getpass.getpass("Confirm password: ") != password:
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

    api = get_settings().api
    uvicorn.run(
        "api.main:create_app", factory=True,
        host=args.host or api.host, port=args.port or api.port,
        reload=args.reload, reload_dirs=[str(PROJECT_ROOT)] if args.reload else None,
        log_config=None,  # keep the application's structured logging
    )
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
    cu.add_argument("--role", action="append", required=True, help="repeatable, e.g. --role HR_ADMIN")
    cu.add_argument("--department", action="append", help="department code scope (repeatable)")
    cu.set_defaults(func=cmd_create_user)

    serve = sub.add_parser("serve", help="start the API server (serves frontend/dist when built)")
    serve.add_argument("--host")
    serve.add_argument("--port", type=int)
    serve.add_argument("--reload", action="store_true", help="development auto-reload")
    serve.set_defaults(func=cmd_serve)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
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
