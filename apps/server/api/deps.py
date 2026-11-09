"""Shared FastAPI dependencies."""

from fastapi import Depends

from server.models.user import User
from server.services.auth import get_current_user
from server.services.credentials import Credentials, resolve_credentials


def get_credentials(user: User = Depends(get_current_user)) -> Credentials:
    """The signed-in user's own keys and settings — what their requests act with
    (plus the server's endpoint for an admin, see resolve_credentials)."""
    return resolve_credentials(user.id, is_admin=user.is_admin)
