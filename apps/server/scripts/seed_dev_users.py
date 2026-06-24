"""Seed the two local dev accounts (admin + user).

Usage (from the repo root):

    uv run python -m server.scripts.seed_dev_users

Idempotent: existing accounts are left untouched. Passwords can be overridden
with the DEV_ADMIN_PASSWORD / DEV_USER_PASSWORD env vars.
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
