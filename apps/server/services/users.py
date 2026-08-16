"""User persistence helpers (lookup, creation, dev seeding)."""

import logging
import os
from typing import Optional

from sqlalchemy.orm import Session

from server.core.config import config
from server.core.security import hash_password
from server.models.user import User, UserRole, AuthProvider


def get_user_by_email(db: Session, email: str) -> Optional[User]:
    return db.query(User).filter(User.email == email.lower()).first()


def get_user_by_oidc_sub(db: Session, sub: str) -> Optional[User]:
    return db.query(User).filter(User.oidc_sub == sub).first()


def create_user(
    db: Session,
    *,
    email: str,
    password: Optional[str] = None,
    role: str = UserRole.USER,
    provider: str = AuthProvider.LOCAL,
    oidc_sub: Optional[str] = None,
) -> User:
    """Create and persist a user. ``password`` is optional (OIDC accounts)."""
    if role not in UserRole.ALL:
        raise ValueError(f"Unknown role '{role}'; expected one of {UserRole.ALL}")
    user = User(
        email=email.lower(),
        hashed_password=hash_password(password) if password else None,
        role=role,
        provider=provider,
        oidc_sub=oidc_sub,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


# Dev accounts created by ``seed_dev_users`` — documented in the README.
# Each password comes from its env var (DEV_ADMIN_PASSWORD / DEV_USER_PASSWORD).
# The weak ``password_default`` is only ever used as a last resort in an
# explicitly-declared development environment (see ``seed_dev_users``); outside
# dev it is refused so a leaked SEED_DEV_USERS can never create known-credential
# admin/user accounts.
DEV_USERS = [
    {
        "email": "admin@example.com",
        "password_env": "DEV_ADMIN_PASSWORD",
        "password_default": "admin1234",
        "role": UserRole.ADMIN,
    },
    {
        "email": "user@example.com",
        "password_env": "DEV_USER_PASSWORD",
        "password_default": "user1234",
        "role": UserRole.USER,
    },
]


def seed_dev_users(
    db: Session, *, allow_insecure_defaults: Optional[bool] = None
) -> int:
    """Create the two dev accounts if they don't already exist (idempotent).

    The password for each account is taken from its env var (DEV_ADMIN_PASSWORD /
    DEV_USER_PASSWORD). When an env var is unset, the weak built-in default is
    only used if ``allow_insecure_defaults`` is true — which defaults to
    :attr:`config.is_development`. Outside an explicitly-declared development
    environment this raises ``RuntimeError`` instead of silently seeding
    known-credential admin/user accounts.

    Returns the number of accounts created. Intended for local development only.
    """
    if allow_insecure_defaults is None:
        allow_insecure_defaults = config.is_development

    created = 0
    for spec in DEV_USERS:
        if get_user_by_email(db, spec["email"]):
            # Seeding never rewrites an existing account, so a stale row keeps
            # whatever password it was created with — a silent skip here is the
            # usual reason "the documented dev password doesn't work".
            logging.info(
                "Dev user %s already exists — left untouched; its password is the "
                "one it was created with, not necessarily %s / the built-in default. "
                "Delete the row to re-seed it.",
                spec["email"],
                spec["password_env"],
            )
            continue
        password = os.getenv(spec["password_env"])
        if not password:
            if not allow_insecure_defaults:
                raise RuntimeError(
                    f"Refusing to seed dev user {spec['email']} with the weak "
                    f"built-in default password outside a development environment. "
                    f"Set {spec['password_env']} to an explicit password, or set "
                    f"ENVIRONMENT=development for local dev."
                )
            password = spec["password_default"]
            logging.warning(
                "Seeding %s with the INSECURE built-in default password "
                "(development only; set %s to override)",
                spec["email"],
                spec["password_env"],
            )
        create_user(
            db,
            email=spec["email"],
            password=password,
            role=spec["role"],
        )
        created += 1
        logging.info("Seeded dev user %s (%s)", spec["email"], spec["role"])
    return created
