"""Dev-only log streaming endpoint.

Mounted by ``main.py`` only when ``DEBUG_LOGS`` is enabled. Streams the server's
own log records to the browser dev console as Server-Sent Events. Each event
payload is a JSON object ``{"source": "fastapi", "line": "..."}`` so the client
can label and colourise lines by origin.
"""

import asyncio
import json
import logging

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from server.core.log_stream import broadcaster

router = APIRouter(prefix="/debug", tags=["debug"])
logger = logging.getLogger(__name__)

# Seconds of silence after which a comment line is sent to keep the connection
# (and any intermediary proxy) from timing the stream out.
_KEEPALIVE_INTERVAL = 15


def _format(line: str) -> str:
    return f"data: {json.dumps({'source': 'fastapi', 'line': line})}\n\n"


@router.get(
    "/logs",
    summary="Stream server logs (SSE)",
    description="Server-Sent Events stream of the FastAPI server logs. "
    "Available only when DEBUG_LOGS is enabled.",
)
async def stream_logs() -> StreamingResponse:
    broadcaster.bind_loop(asyncio.get_running_loop())
    queue = broadcaster.subscribe()

    async def event_generator():
        try:
            # Replay the recent backlog so a late client has context.
            for line in broadcaster.snapshot():
                yield _format(line)
            while True:
                try:
                    line = await asyncio.wait_for(
                        queue.get(), timeout=_KEEPALIVE_INTERVAL
                    )
                    yield _format(line)
                except asyncio.TimeoutError:
                    yield ": keep-alive\n\n"
        finally:
            broadcaster.unsubscribe(queue)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            # Disable proxy buffering (nginx) so events flush immediately.
            "X-Accel-Buffering": "no",
        },
    )
