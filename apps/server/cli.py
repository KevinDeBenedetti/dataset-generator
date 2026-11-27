"""Operator commands, run inside the deployment (``kubectl exec``, ``docker exec``):

    python -m server.cli migrate            # apply the database migrations (a deploy step)
    python -m server.cli claim-legacy       # to the admin of ADMIN_USERNAME
    python -m server.cli claim-legacy --email you@example.com
    python -m server.cli hash-password      # an ADMIN_PASSWORD_HASH value
    python -m server.cli gen-key            # a new SECRETS_ENCRYPTION_KEYS entry
    python -m server.cli rewrap-secrets     # after rotating that key ring

Kept separate from the HTTP API on purpose: these act with database privileges
and no session, so they are not reachable from the network.
"""

import argparse
import sys
from typing import List, Optional

from server.core.database import SessionLocal


def _claim_legacy(email: Optional[str]) -> int:
    from server.services.legacy import claim_legacy_rows

    db = SessionLocal()
    try:
        if not email:
            from server.auth.admin_secrets import ensure_admin_account

            admin = ensure_admin_account(db)
            if admin is None:
                print(
                    "error: no --email and no ADMIN_USERNAME admin to give it to",
                    file=sys.stderr,
                )
                return 1
            email = admin.email or ""
        try:
            counts = claim_legacy_rows(db, email)
        except ValueError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
    finally:
        db.close()
    if not any(counts.values()):
        print("Nothing to claim: no data is held by the system user.")
    else:
        print(
            f"Assigned to {email}: " + ", ".join(f"{n} {k}" for k, n in counts.items())
        )
    return 0


def _migrate() -> int:
    """Apply the Alembic migrations to DATABASE_URL, under the advisory lock.

    What a Kubernetes pre-upgrade Job runs (with RUN_MIGRATIONS_ON_STARTUP=false
    on the pods); idempotent, and safe to run twice at once.
    """
    from server.core.database import SQLALCHEMY_DATABASE_URL
    from server.migrations.utils.db_utils import upgrade_db

    upgrade_db(SQLALCHEMY_DATABASE_URL)
    print("Database is up to date.")
    return 0


def _gen_key() -> int:
    from datetime import date

    from server.core.crypto import generate_key

    # "id:key" — the id only has to be unique in the ring; the date says when.
    print(f"k{date.today():%Y%m%d}:{generate_key()}")
    return 0


def _rewrap_secrets() -> int:
    """Re-encrypt every stored secret under the primary key of the ring."""
    from server.services.user_secrets import rewrap_all

    db = SessionLocal()
    try:
        counts = rewrap_all(db)
    finally:
        db.close()
    print(", ".join(f"{n} {k}" for k, n in counts.items()))
    return 1 if counts["failed"] else 0


def _hash_password() -> int:
    """Prompt for the admin's password (twice) and print its argon2id hash."""
    import getpass

    from server.auth.admin_secrets import hash_password

    password = getpass.getpass("Admin password: ")
    if len(password) < 12:
        print("error: use at least 12 characters", file=sys.stderr)
        return 1
    if getpass.getpass("Again: ") != password:
        print("error: the two passwords differ", file=sys.stderr)
        return 1
    print(hash_password(password))
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m server.cli")
    commands = parser.add_subparsers(dest="command", required=True)
    claim = commands.add_parser(
        "claim-legacy",
        help="give the data that predates per-user ownership to an account",
    )
    claim.add_argument(
        "--email",
        help="the account that takes over (default: the admin of ADMIN_USERNAME)",
    )
    commands.add_parser(
        "migrate", help="apply the database migrations (what a deploy Job runs)"
    )
    commands.add_parser(
        "hash-password", help="print the ADMIN_PASSWORD_HASH of a password typed in"
    )
    commands.add_parser(
        "gen-key", help="print a new key for SECRETS_ENCRYPTION_KEYS (id:key)"
    )
    commands.add_parser(
        "rewrap-secrets",
        help="re-encrypt every stored secret under the ring's first key "
        "(after prepending a new key to SECRETS_ENCRYPTION_KEYS)",
    )
    args = parser.parse_args(argv)
    if args.command == "claim-legacy":
        return _claim_legacy(args.email)
    if args.command == "migrate":
        return _migrate()
    if args.command == "hash-password":
        return _hash_password()
    if args.command == "gen-key":
        return _gen_key()
    if args.command == "rewrap-secrets":
        return _rewrap_secrets()
    return 2  # pragma: no cover — argparse rejects unknown commands


if __name__ == "__main__":
    raise SystemExit(main())
