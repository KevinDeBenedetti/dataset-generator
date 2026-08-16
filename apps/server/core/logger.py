import logging

from server.core.log_stream import BroadcastLogHandler

# Compact format for the dev log console (the SSE stream / browser terminal).
_STREAM_FORMAT = "%(asctime)s | %(levelname)s | %(name)s | %(message)s"


def setup_logging(level: int = logging.INFO):
    logging.basicConfig(
        level=level,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s - %(pathname)s:%(lineno)d",
        handlers=[logging.StreamHandler(), logging.FileHandler("scraper.log")],
    )

    # Mirror every record into the in-memory broadcaster so the dev log console
    # (DEBUG_LOGS=1) can stream them over SSE. Cheap when no client is connected
    # (just a deque append), so it is always attached.
    if not any(
        isinstance(h, BroadcastLogHandler) for h in logging.getLogger().handlers
    ):
        broadcast_handler = BroadcastLogHandler()
        broadcast_handler.setFormatter(logging.Formatter(_STREAM_FORMAT))
        logging.getLogger().addHandler(broadcast_handler)
