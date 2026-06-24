"""User persistence helpers (lookup, creation, dev seeding)."""

import logging
import os
from typing import Optional

from sqlalchemy.orm import Session

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
# Override the passwords via env (DEV_ADMIN_PASSWORD / DEV_USER_PASSWORD) so the
# defaults below never need to be the real ones in any shared environment.
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


def seed_dev_users(db: Session) -> int:
    """Create the two dev accounts if they don't already exist (idempotent).

    Returns the number of accounts created. Intended for local development only.
    """
    created = 0
    for spec in DEV_USERS:
        if get_user_by_email(db, spec["email"]):
            continue
        password = os.getenv(spec["password_env"], spec["password_default"])
        create_user(
            db,
            email=spec["email"],
            password=password,
            role=spec["role"],
        )
        created += 1
        logging.info("Seeded dev user %s (%s)", spec["email"], spec["role"])
    return created
