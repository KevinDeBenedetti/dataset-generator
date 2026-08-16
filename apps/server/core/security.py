"""Password hashing helpers.

Thin wrapper around ``bcrypt`` so the rest of the codebase never touches the
raw library. Bcrypt truncates input at 72 bytes, so we guard against that
explicitly rather than relying on silent truncation.
"""

import bcrypt

# Bcrypt only considers the first 72 bytes of the password.
_BCRYPT_MAX_BYTES = 72


def hash_password(password: str) -> str:
    """Return a bcrypt hash (UTF-8 string) for ``password``."""
    pwd_bytes = password.encode("utf-8")[:_BCRYPT_MAX_BYTES]
    return bcrypt.hashpw(pwd_bytes, bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, hashed: str) -> bool:
    """Return True if ``password`` matches the stored bcrypt ``hashed`` value."""
    if not hashed:
        return False
    pwd_bytes = password.encode("utf-8")[:_BCRYPT_MAX_BYTES]
    try:
        return bcrypt.checkpw(pwd_bytes, hashed.encode("utf-8"))
    except (ValueError, TypeError):
        # Malformed/empty hash (e.g. an OIDC-only account with no password).
        return False
