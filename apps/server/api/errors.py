"""One way to answer an unexpected failure.

A 5xx answer never carries the exception's text: it can name SQL, internal
URLs or a provider's request ids. The exception is logged with its traceback,
and the client gets what failed, in words.
"""

import logging

from fastapi import HTTPException

logger = logging.getLogger("server.api")


def internal_error(what: str, status_code: int = 500) -> HTTPException:
    """Log the exception being handled; an HTTPException saying ``what`` failed.

    Call it from an ``except`` block: ``raise internal_error("Deleting the dataset")``.
    """
    logger.exception("%s failed", what)
    return HTTPException(
        status_code=status_code,
        detail=f"{what} failed. Try again; if it keeps failing, the server logs say why.",
    )
