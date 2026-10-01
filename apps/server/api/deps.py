"""Shared FastAPI dependencies."""

from fastapi import Depends

from server.models.user import User
from server.services.auth import get_current_user
from server.services.credentials import Credentials, resolve_credentials


def get_credentials(user: User = Depends(get_current_user)) -> Credentials:
    """The signed-in user's own keys and settings — what their requests act with."""
    return resolve_credentials(user.id)
