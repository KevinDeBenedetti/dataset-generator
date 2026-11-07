"""Password hashing helpers.

Thin wrapper around ``bcrypt`` so the rest of the codebase never touches the
raw library. Bcrypt only reads the first 72 bytes of a password: a longer one
is refused when it is set (``hash_password``), never silently cut.
"""

import bcrypt

# Bcrypt only reads the first 72 bytes of the password.
MAX_PASSWORD_BYTES = 72


def password_too_long(password: str) -> bool:
    """True when bcrypt can't take all of ``password`` (its UTF-8 bytes)."""
    return len(password.encode("utf-8")) > MAX_PASSWORD_BYTES


def hash_password(password: str) -> str:
    """Return a bcrypt hash (UTF-8 string) for ``password``.

    Raises ``ValueError`` for a password longer than 72 bytes: bcrypt would
    ignore the rest, and any password sharing those 72 bytes would match.
    """
    if password_too_long(password):
        raise ValueError(
            f"A password can't be longer than {MAX_PASSWORD_BYTES} bytes "
            "(UTF-8): bcrypt would ignore the rest"
        )
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, hashed: str) -> bool:
    """Return True if ``password`` matches the stored bcrypt ``hashed`` value.

    A password over 72 bytes is compared by its first 72, as bcrypt always
    did: no new hash comes from one (``hash_password`` refuses it), but an
    account hashed before that limit keeps logging in.
    """
    if not hashed:
        return False
    pwd_bytes = password.encode("utf-8")[:MAX_PASSWORD_BYTES]
    try:
        return bcrypt.checkpw(pwd_bytes, hashed.encode("utf-8"))
    except (ValueError, TypeError):
        # Malformed/empty hash (e.g. an OIDC-only account with no password).
        return False
