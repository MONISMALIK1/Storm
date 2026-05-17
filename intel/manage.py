"""Management CLI for the intelligence pipeline.

Examples:
    python -m intel.manage init-db
    python -m intel.manage create-admin --email admin@tow.local --password ChangeMe123
    python -m intel.manage ingest
    python -m intel.manage scan
    python -m intel.manage serve --host 0.0.0.0 --port 8000
    python -m intel.manage agent --brief
    python -m intel.manage agent --task "What are the top competitor threats?"
    python -m intel.manage agent           # interactive REPL
"""
from __future__ import annotations

import argparse
import getpass
import json
import sys


def cmd_init_db(_args) -> int:
    from .db import init_db
    init_db()
    print("Database initialized.")
    return 0


def cmd_create_admin(args) -> int:
    from .auth import create_user
    password = args.password or getpass.getpass("Password: ")
    try:
        user = create_user(args.email, password, role=args.role)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    print(f"Created {user.role} user #{user.id}: {user.email}")
    return 0


def cmd_ingest(_args) -> int:
    from .db import init_db
    from .ingest import ingest_all
    init_db()
    result = ingest_all()
    print(json.dumps(result, indent=2))
    return 0


def cmd_scan(_args) -> int:
    from .alerts import run_detection
    from .db import init_db
    init_db()
    new = run_detection()
    print(f"{len(new)} new alert(s)")
    for a in new:
        print(f"  [{a['priority']}] {a['subject']}")
    return 0


def cmd_agent(args) -> int:
    """Launch the LangGraph CI agent."""
    from .agent.cli import main as agent_main
    argv: list[str] = []
    if getattr(args, "task", None):
        argv += ["--task", args.task]
    if getattr(args, "brief", False):
        argv.append("--brief")
    if getattr(args, "alerts", False):
        argv.append("--alerts")
    if getattr(args, "strategy", False):
        argv.append("--strategy")
    if getattr(args, "diagram", False):
        argv.append("--diagram")
    if getattr(args, "verbose", False):
        argv.append("--verbose")
    return agent_main(argv or None)


def cmd_serve(args) -> int:
    import uvicorn
    uvicorn.run(
        "intel.api:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
        log_level="info",
    )
    return 0


def cmd_list_users(_args) -> int:
    from sqlalchemy import select
    from .db import User, session_scope
    with session_scope() as s:
        for u in s.scalars(select(User).order_by(User.id)):
            print(f"#{u.id:<3} {u.role:<12} {u.email}  active={u.is_active}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="intel.manage")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("init-db", help="Create database tables")

    p_admin = sub.add_parser("create-admin", help="Create a user")
    p_admin.add_argument("--email", required=True)
    p_admin.add_argument("--password", help="(prompted if omitted)")
    p_admin.add_argument("--role", default="admin", choices=("super_admin", "admin", "analyst", "viewer"))

    sub.add_parser("ingest", help="Pull CSVs + gmap SQLite into unified DB")
    sub.add_parser("scan", help="Run alert detection over recent data")
    sub.add_parser("users", help="List all users")

    p_agent = sub.add_parser("agent", help="Run the LangGraph CI agent")
    p_agent.add_argument("--task", "-t", help="Single intelligence query")
    p_agent.add_argument("--brief", "-b", action="store_true", help="Daily executive brief")
    p_agent.add_argument("--alerts", "-a", action="store_true", help="Alert scan")
    p_agent.add_argument("--strategy", "-s", action="store_true", help="Strategic recommendations")
    p_agent.add_argument("--diagram", action="store_true", help="Print graph topology")
    p_agent.add_argument("--verbose", "-v", action="store_true", help="Show timing + token details")

    p_serve = sub.add_parser("serve", help="Run the API server")
    p_serve.add_argument("--host", default="127.0.0.1")
    p_serve.add_argument("--port", type=int, default=8000)
    p_serve.add_argument("--reload", action="store_true")

    args = parser.parse_args(argv)
    handlers = {
        "init-db": cmd_init_db,
        "create-admin": cmd_create_admin,
        "ingest": cmd_ingest,
        "scan": cmd_scan,
        "users": cmd_list_users,
        "agent": cmd_agent,
        "serve": cmd_serve,
    }
    return handlers[args.cmd](args)


if __name__ == "__main__":
    raise SystemExit(main())
