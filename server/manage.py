"""Command-line admin tasks.

    python -m server.manage add-user <user id> --role admin|editor|viewer [--name "Full Name"]
    python -m server.manage reset-password <user id>
    python -m server.manage import <Master Sheet.xlsx>      (loads a Master Sheet straight into the database)
"""
from __future__ import annotations

import argparse
import getpass
import sys
from pathlib import Path

from sqlalchemy import select, update

from mis_reports.pipeline import load_aliases as csv_aliases

from . import auth, db, imports
from .config import Settings


def _password() -> str:
    while True:
        p1 = getpass.getpass("New password: ")
        if len(p1) < auth.MIN_PASSWORD:
            print(f"Use at least {auth.MIN_PASSWORD} characters.")
            continue
        if p1 == getpass.getpass("Repeat it: "):
            return p1
        print("The two passwords are different.")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m server.manage")
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("add-user")
    a.add_argument("username")
    a.add_argument("--role", choices=db.ROLES, required=True)
    a.add_argument("--name", default="")
    r = sub.add_parser("reset-password")
    r.add_argument("username")
    i = sub.add_parser("import")
    i.add_argument("path", type=Path)
    args = ap.parse_args(argv)

    settings = Settings()
    engine = db.make_engine(settings.database_url)
    db.init_db(engine, alias_seed=csv_aliases())
    name = getattr(args, "username", "").strip().lower()

    if args.cmd == "add-user":
        with engine.begin() as conn:
            if conn.execute(select(db.users.c.id).where(db.users.c.username == name)).first():
                print(f"User '{name}' already exists.")
                return 1
            conn.execute(db.users.insert().values(username=name, full_name=args.name,
                                                  password_hash=auth.hash_password(_password()), role=args.role,
                                                  active=True, created_at=db.utcnow()))
        print(f"Added {name} ({args.role}).")
    elif args.cmd == "reset-password":
        with engine.begin() as conn:
            u = conn.execute(select(db.users).where(db.users.c.username == name)).first()
            if u is None:
                print(f"No user '{name}'.")
                return 1
            conn.execute(update(db.users).where(db.users.c.id == u.id).values(
                password_hash=auth.hash_password(_password()), failed_logins=0, locked_until=None,
                token_version=u.token_version + 1))
        print(f"Password changed for {name}.")
    elif args.cmd == "import":
        with engine.connect() as conn:
            u = conn.execute(select(db.users).where(db.users.c.role == "admin")).first()
        if u is None:
            print("Add an admin first (add-user ... --role admin).")
            return 1
        user = {"id": u.id, "username": u.username}
        batch = imports.create_preview(engine, settings, user, args.path.name, args.path.read_bytes())
        imports.confirm(engine, settings, user, batch["id"])
        print("Imported:", ", ".join(f"{k} {v}" for k, v in batch["summary"]["counts"].items()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
