"""Operator commands, run inside the deployment (``kubectl exec``, ``docker exec``):

    python -m server.cli migrate            # apply the database migrations (a deploy step)
    python -m server.cli claim-legacy --email you@example.com
    python -m server.cli promote-admin you@example.com
    python -m server.cli gen-key            # a new SECRETS_ENCRYPTION_KEYS entry
    python -m server.cli rewrap-secrets     # after rotating that key ring

Kept separate from the HTTP API on purpose: these act with database privileges
and no session, so they are not reachable from the network.
"""

import argparse
import sys
from typing import List, Optional

from server.core.database import SessionLocal


def _claim_legacy(email: str) -> int:
    from server.services.legacy import claim_legacy_rows

    db = SessionLocal()
    try:
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


def _promote_admin(email: str) -> int:
    """Break-glass: make an account admin from inside the deployment."""
    from server.models.user import UserRole
    from server.services import audit
    from server.services.users import get_user_by_email

    db = SessionLocal()
    try:
        user = get_user_by_email(db, email)
        if user is None:
            print(f"error: no account with the email '{email}'", file=sys.stderr)
            return 1
        if user.role != UserRole.ADMIN:
            user.role = UserRole.ADMIN
            user.is_active = True
            audit.record(db, "user.promoted", target=user, detail={"reason": "cli"})
        print(f"{email} is an admin.")
        return 0
    finally:
        db.close()


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m server.cli")
    commands = parser.add_subparsers(dest="command", required=True)
    claim = commands.add_parser(
        "claim-legacy",
        help="give the data that predates per-user ownership to an account",
    )
    claim.add_argument("--email", required=True, help="the account that takes over")
    commands.add_parser(
        "migrate", help="apply the database migrations (what a deploy Job runs)"
    )
    promote = commands.add_parser(
        "promote-admin", help="make an account admin (break-glass, audited)"
    )
    promote.add_argument("email")
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
    if args.command == "promote-admin":
        return _promote_admin(args.email)
    if args.command == "gen-key":
        return _gen_key()
    if args.command == "rewrap-secrets":
        return _rewrap_secrets()
    return 2  # pragma: no cover — argparse rejects unknown commands


if __name__ == "__main__":
    raise SystemExit(main())
