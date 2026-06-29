"""Seed the two local dev accounts (admin + user).

Usage (from the repo root):

    uv run python -m server.scripts.seed_dev_users

Idempotent: existing accounts are left untouched. Each password is taken from
its env var (DEV_ADMIN_PASSWORD / DEV_USER_PASSWORD). Outside an explicitly
declared development environment (ENVIRONMENT=development) those env vars are
required: seeding refuses the weak built-in defaults rather than create
known-credential accounts.
"""

import logging

from server.core.database import SessionLocal
from server.services.users import seed_dev_users


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    db = SessionLocal()
    try:
        created = seed_dev_users(db)
        print(f"Done. Created {created} dev user(s) (existing ones skipped).")
    finally:
        db.close()


if __name__ == "__main__":
    main()
