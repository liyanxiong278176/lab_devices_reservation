import asyncio
from types import SimpleNamespace

import httpx
import pytest
from app.core.admission import RequestCapacityMiddleware
from app.core.metrics import MetricsRegistry
from app.core.request_id import RequestIdMiddleware
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


@pytest.mark.asyncio
async def test_bounded_queue_waits_for_capacity_and_rejects_only_overflow() -> None:
    app = FastAPI()
    release = asyncio.Event()
    started: list[int] = []

    @app.get("/work/{request_id}")
    async def work(request_id: int) -> dict[str, bool]:
        started.append(request_id)
        await release.wait()
        return {"ok": True}

    middleware = RequestCapacityMiddleware(app, capacity=1, queue_capacity=1)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=middleware),
        base_url="http://test",
    ) as client:
        active = asyncio.create_task(client.get("/work/1"))
        while started != [1]:
            await asyncio.sleep(0)

        queued = asyncio.create_task(client.get("/work/2"))
        while middleware.gate.waiting != 1:
            await asyncio.sleep(0)

        overflow = await client.get("/work/3")
        assert overflow.status_code == 503
        assert overflow.json()["code"] == "SERVICE_BUSY"
        assert started == [1]

        release.set()
        active_response, queued_response = await asyncio.gather(active, queued)

    assert active_response.status_code == 200
    assert queued_response.status_code == 200
    assert started == [1, 2]
    assert middleware.gate.waiting == 0


@pytest.mark.asyncio
async def test_long_lived_stream_does_not_consume_database_request_capacity() -> None:
    app = FastAPI()
    stream_started = asyncio.Event()
    stream_release = asyncio.Event()

    @app.get("/stream")
    async def stream() -> dict[str, bool]:
        stream_started.set()
        await stream_release.wait()
        return {"ok": True}

    @app.get("/work")
    async def work() -> dict[str, bool]:
        return {"ok": True}

    middleware = RequestCapacityMiddleware(app, capacity=1, bypass_paths={"/stream"})
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=middleware),
        base_url="http://test",
    ) as client:
        active_stream = asyncio.create_task(client.get("/stream"))
        await stream_started.wait()
        work_response = await client.get("/work")
        assert work_response.status_code == 200
        stream_release.set()
        stream_response = await active_stream

    assert stream_response.status_code == 200


@pytest.mark.asyncio
async def test_cancelled_queued_request_does_not_leak_queue_capacity() -> None:
    app = FastAPI()
    release = asyncio.Event()
    started = asyncio.Event()

    @app.get("/work")
    async def work() -> dict[str, bool]:
        started.set()
        await release.wait()
        return {"ok": True}

    middleware = RequestCapacityMiddleware(app, capacity=1, queue_capacity=1)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=middleware),
        base_url="http://test",
    ) as client:
        active = asyncio.create_task(client.get("/work"))
        await started.wait()
        queued = asyncio.create_task(client.get("/work"))
        while middleware.gate.waiting != 1:
            await asyncio.sleep(0)
        queued.cancel()
        with pytest.raises(asyncio.CancelledError):
            await queued
        assert middleware.gate.waiting == 0

        release.set()
        assert (await active).status_code == 200

        next_request = await client.get("/work")
        assert next_request.status_code == 200


@pytest.mark.asyncio
async def test_admission_wait_is_reported_separately_from_service_time() -> None:
    app = FastAPI()
    app.state.metrics = MetricsRegistry()
    app.state.settings = SimpleNamespace(api_prefix="/api/v2")
    release = asyncio.Event()
    started = asyncio.Event()

    @app.get("/work")
    async def work() -> dict[str, bool]:
        started.set()
        await release.wait()
        return {"ok": True}

    capacity = RequestCapacityMiddleware(app, capacity=1, queue_capacity=1)
    metrics_app = RequestIdMiddleware(capacity)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=metrics_app),
        base_url="http://test",
    ) as client:
        first = asyncio.create_task(client.get("/work"))
        await started.wait()
        second = asyncio.create_task(client.get("/work"))
        while capacity.gate.waiting != 1:
            await asyncio.sleep(0)
        await asyncio.sleep(0.02)
        release.set()
        responses = await asyncio.gather(first, second)

    assert [response.status_code for response in responses] == [200, 200]
    metrics = app.state.metrics.render_prometheus()
    assert (
        'http_request_admission_wait_seconds_count{gate="api",method="GET",'
        'result="admitted",route="/work"} 2.0'
    ) in metrics
    assert (
        'http_request_service_seconds_count{method="GET",route="/work"} 2.0'
    ) in metrics
    assert (
        'http_request_admission_wait_seconds_sum{gate="api",method="GET",'
        'result="admitted",route="/work"} '
    ) in metrics


@pytest.mark.asyncio
async def test_non_http_scopes_bypass_admission_gates() -> None:
    seen: list[str] = []

    async def app(scope, _receive, _send) -> None:
        seen.append(scope["type"])

    middleware = RequestCapacityMiddleware(app, capacity=1)
    for scope_type in ("websocket", "lifespan"):
        await middleware({"type": scope_type}, None, None)

    assert seen == ["websocket", "lifespan"]


@pytest.mark.asyncio
async def test_request_id_middleware_works_when_metrics_are_not_configured() -> None:
    app = FastAPI()
    app.add_middleware(RequestIdMiddleware)

    @app.get("/plain")
    async def plain() -> dict[str, bool]:
        return {"ok": True}

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.get("/plain")

    assert response.status_code == 200
    assert response.headers["X-Request-ID"]
