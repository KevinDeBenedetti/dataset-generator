"""``python -m server.worker`` — executes the queued dataset jobs (services/queue.py).

Run as many as you like (one Deployment, N replicas): claims never overlap.
SIGTERM/SIGINT stop claiming and drain the runs in progress.
"""

import asyncio
import signal

from server.core import logger as logger_module
from server.services.queue import run_forever


async def _main() -> None:
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stop.set)
    await run_forever(stop)


def main() -> None:
    logger_module.setup_logging()
    asyncio.run(_main())


if __name__ == "__main__":
    main()
