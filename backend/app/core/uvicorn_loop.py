"""Platform event-loop factory used by both reload and production Uvicorn."""

import asyncio
import sys


def platform_loop_factory() -> asyncio.AbstractEventLoop:
    """Avoid Windows selector's fixed socket-set limit under concurrent load."""
    if sys.platform == "win32":
        return asyncio.ProactorEventLoop()
    return asyncio.new_event_loop()
