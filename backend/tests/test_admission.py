import asyncio

import httpx
import pytest
from app.core.admission import RequestCapacityMiddleware
from fastapi import FastAPI


@pytest.mark.asyncio
async def test_liveness_has_an_independent_bounded_capacity() -> None:
    app = FastAPI()
    live_release = asyncio.Event()
    work_release = asyncio.Event()
    two_live_started = asyncio.Event()
    one_work_started = asyncio.Event()
    live_started = 0
    work_started = 0

    @app.get("/live")
    async def live() -> dict[str, bool]:
        nonlocal live_started
        live_started += 1
        if live_started == 2:
            two_live_started.set()
        await live_release.wait()
        return {"ok": True}

    @app.get("/work")
    async def work() -> dict[str, bool]:
        nonlocal work_started
        work_started += 1
        one_work_started.set()
        await work_release.wait()
        return {"ok": True}

    app.add_middleware(
        RequestCapacityMiddleware,
        capacity=1,
        exempt_paths={"/live"},
        exempt_capacity=2,
    )

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        live_tasks = [asyncio.create_task(client.get("/live")) for _ in range(2)]
        await asyncio.wait_for(two_live_started.wait(), timeout=1)
        work_task = asyncio.create_task(client.get("/work"))
        await asyncio.wait_for(one_work_started.wait(), timeout=1)

        rejected_live = await client.get("/live")
        rejected_work = await client.get("/work")
        assert rejected_live.status_code == 503
        assert rejected_live.headers["Retry-After"] == "1"
        assert rejected_work.status_code == 503
        assert live_started == 2
        assert work_started == 1

        live_release.set()
        work_release.set()
        completed = await asyncio.gather(*live_tasks, work_task)

    assert [response.status_code for response in completed] == [200, 200, 200]
