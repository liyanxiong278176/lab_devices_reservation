import asyncio
import sys

from app.core.uvicorn_loop import platform_loop_factory


def test_platform_loop_factory_uses_socket_scalable_windows_loop() -> None:
    loop = platform_loop_factory()
    try:
        if sys.platform == "win32":
            assert isinstance(loop, asyncio.ProactorEventLoop)
        else:
            assert isinstance(loop, asyncio.SelectorEventLoop)
    finally:
        loop.close()
