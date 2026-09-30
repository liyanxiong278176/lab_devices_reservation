import asyncio
from types import SimpleNamespace

import pytest
from app.core.settings import Settings
from app.main import create_app
from fastapi.testclient import TestClient
from httpx import ASGITransport, AsyncClient
from sqlalchemy.exc import OperationalError
from sqlalchemy.exc import TimeoutError as SQLAlchemyTimeoutError


def test_live_returns_v2_envelope_and_request_id() -> None:
    client = TestClient(
        create_app(
            Settings(
                environment="test",
                debug=True,
                cors_origins=[],
            )
        )
    )

    response = client.get("/api/v2/live")

    assert response.status_code == 200
    assert response.headers["X-Request-ID"]
    assert response.json() == {
        "code": "OK",
        "message": "success",
        "data": {"status": "ok"},
        "request_id": response.headers["X-Request-ID"],
    }


def test_client_request_id_is_preserved() -> None:
    client = TestClient(create_app(Settings(environment="test", cors_origins=[])))

    response = client.get("/api/v2/ready", headers={"X-Request-ID": "req-test-001"})

    assert response.status_code == 401
    assert response.headers["X-Request-ID"] == "req-test-001"
    assert response.json()["request_id"] == "req-test-001"


def test_readiness_is_not_public_and_metrics_require_a_scrape_secret() -> None:
    token = "t" * 40
    app = create_app(Settings(environment="test", cors_origins=[], metrics_token=token))
    client = TestClient(app)
    assert client.get("/api/v2/ready").status_code == 401
    assert client.get("/api/v2/metrics").status_code == 401
    metrics_response = client.get(
        "/api/v2/metrics",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert metrics_response.status_code == 200
    assert metrics_response.headers["content-type"].startswith("text/plain; version=")
    assert 'route="/api/v2/metrics"' not in metrics_response.text
    assert 'route="/metrics"' not in metrics_response.text


def test_business_errors_keep_their_http_status_and_envelope() -> None:
    client = TestClient(create_app(Settings(environment="test", cors_origins=[])))

    response = client.get("/api/v2/devices")

    assert response.status_code == 401
    assert response.json()["code"] == "AUTH_REQUIRED"
    assert response.json()["data"] is None


def test_sqlalchemy_pool_timeout_is_reported_as_retryable_overload() -> None:
    app = create_app(Settings(environment="test", cors_origins=[]))

    async def simulate_pool_timeout():
        raise SQLAlchemyTimeoutError("pool limit reached")

    app.add_api_route("/test-pool-timeout", simulate_pool_timeout)
    client = TestClient(app, raise_server_exceptions=False)

    response = client.get("/test-pool-timeout")

    assert response.status_code == 503
    assert response.headers["Retry-After"] == "1"
    assert response.json()["code"] == "SERVICE_BUSY"


def test_database_connection_failure_is_reported_as_retryable_dependency_error() -> None:
    app = create_app(Settings(environment="test", cors_origins=[]))

    async def simulate_mysql_connection_failure():
        raise OperationalError("SELECT 1", {}, OSError("connection refused"))

    app.add_api_route("/test-database-connection-failure", simulate_mysql_connection_failure)
    client = TestClient(app, raise_server_exceptions=False)

    response = client.get("/test-database-connection-failure")

    assert response.status_code == 503
    assert response.json()["code"] == "DEPENDENCY_UNAVAILABLE"
    assert response.headers["X-Request-ID"]


def test_unmatched_paths_share_a_bounded_metrics_label() -> None:
    token = "m" * 40
    app = create_app(Settings(environment="test", cors_origins=[], metrics_token=token))
    client = TestClient(app)

    assert client.get("/random-404-one").status_code == 404
    assert client.get("/random-404-two").status_code == 404
    metrics_response = client.get(
        "/api/v2/metrics",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert metrics_response.status_code == 200
    metrics = metrics_response.text

    assert 'route="__unmatched__"' in metrics
    assert "/random-404-one" not in metrics
    assert "/random-404-two" not in metrics


def test_metrics_are_disabled_without_scrape_token_and_bound_method_labels() -> None:
    token = "s" * 40
    app = create_app(Settings(environment="test", cors_origins=[], metrics_token=token))
    client = TestClient(app)
    assert client.get("/api/v2/metrics").status_code == 401

    for index in range(20):
        response = client.request(f"CUSTOM-{index}", "/not-a-route")
        assert response.status_code == 404

    metrics = client.get(
        "/api/v2/metrics",
        headers={"Authorization": f"Bearer {token}"},
    ).text
    assert 'method="OTHER"' in metrics
    assert "CUSTOM-0" not in metrics
    assert "CUSTOM-19" not in metrics


def test_metrics_registry_has_a_hard_series_limit() -> None:
    from app.core.metrics import MetricsRegistry

    registry = MetricsRegistry(max_series=3)
    for index in range(10):
        registry.increment("untrusted_labels_total", labels={"value": index})
    assert len(registry._series) == 3
    metrics = registry.render_prometheus()
    assert 'untrusted_labels_total{value="0"} 1.0' in metrics
    assert 'untrusted_labels_total{value="1"} 1.0' in metrics
    assert 'untrusted_labels_total{value="2"} 1.0' in metrics
    assert 'untrusted_labels_total{value="3"}' not in metrics


def test_metrics_counter_and_histogram_use_prometheus_exposition_format() -> None:
    from app.core.metrics import MetricsRegistry

    registry = MetricsRegistry()
    registry.increment("lab_test_requests", labels={"route": "/devices"})
    registry.observe("lab_test_latency_seconds", 0.2, labels={"route": "/devices"})

    metrics = registry.render_prometheus()

    assert 'lab_test_requests_total{route="/devices"} 1.0' in metrics
    assert 'lab_test_latency_seconds_bucket{le="0.25",route="/devices"} 1.0' in metrics
    assert 'lab_test_latency_seconds_count{route="/devices"} 1.0' in metrics


def test_database_pool_metrics_expose_pool_usage() -> None:
    from app.core.metrics import MetricsRegistry

    class Pool:
        def size(self) -> int:
            return 12

        def checkedout(self) -> int:
            return 3

        def overflow(self) -> int:
            return 1

    registry = MetricsRegistry()
    registry.monitor_sqlalchemy_pool(SimpleNamespace(sync_engine=SimpleNamespace(pool=Pool())))

    metrics = registry.render_prometheus()

    assert "lab_db_pool_size 12.0" in metrics
    assert "lab_db_pool_checked_out 3.0" in metrics
    assert "lab_db_pool_overflow 1.0" in metrics


def test_database_pool_overflow_metric_clamps_unused_pool_slots_to_zero() -> None:
    from app.core.metrics import MetricsRegistry

    class UnderfilledPool:
        def size(self) -> int:
            return 10

        def checkedout(self) -> int:
            return 0

        def overflow(self) -> int:
            return -7

    registry = MetricsRegistry()
    registry.monitor_sqlalchemy_pool(UnderfilledPool())

    metrics = registry.render_prometheus()

    assert "lab_db_pool_overflow 0.0" in metrics


@pytest.mark.asyncio
async def test_database_statement_metrics_record_duration_without_sql_labels() -> None:
    from app.core.metrics import MetricsRegistry
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    registry = MetricsRegistry()
    registry.monitor_sqlalchemy_pool(engine)
    async with engine.connect() as connection:
        await connection.execute(text("SELECT 1"))
    metrics = registry.render_prometheus()
    await engine.dispose()

    assert 'db_statements_total{operation="SELECT"} 1.0' in metrics
    assert 'db_statement_duration_seconds_count{operation="SELECT"} 1.0' in metrics
    assert "SELECT 1" not in metrics


def test_http_metrics_expose_exact_status_for_separating_overload_from_faults() -> None:
    from starlette.responses import JSONResponse

    token = "overload-metrics-test-token-1234567890"
    app = create_app(Settings(environment="test", cors_origins=[], metrics_token=token))

    async def service_busy() -> JSONResponse:
        return JSONResponse({"code": "SERVICE_BUSY"}, status_code=503)

    app.add_api_route("/test-service-busy", service_busy)
    client = TestClient(app)

    response = client.get("/test-service-busy")
    metrics_response = client.get(
        "/api/v2/metrics",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 503
    assert metrics_response.status_code == 200
    assert (
        'http_requests_total{method="GET",route="/test-service-busy",status="503",'
        'status_class="5xx"} 1.0'
    ) in metrics_response.text


@pytest.mark.asyncio
async def test_cache_invalidation_metric_does_not_export_tenant_identifier() -> None:
    from app.core.metrics import MetricsRegistry
    from app.infrastructure.cache.cache import CacheService

    class RedisStub:
        async def incr(self, key: str) -> int:
            assert key.endswith("college:987654")
            return 2

    registry = MetricsRegistry()
    cache = CacheService(RedisStub(), SimpleNamespace(), registry)  # type: ignore[arg-type]

    assert await cache.bump_version("college:987654")
    metrics = registry.render_prometheus()

    assert 'cache_invalidations_total{scope="college"} 1.0' in metrics
    assert "987654" not in metrics


@pytest.mark.asyncio
async def test_bounded_queue_absorbs_one_request_and_live_stays_available() -> None:
    app = create_app(
        Settings(
            environment="test",
            cors_origins=["http://localhost:5173"],
            db_pool_size=1,
            db_max_overflow=1,
            request_queue_capacity=1,
        )
    )
    release = asyncio.Event()
    both_entered = asyncio.Event()
    entered = 0

    async def hold_request() -> dict[str, bool]:
        nonlocal entered
        entered += 1
        if entered >= 2:
            both_entered.set()
        await release.wait()
        return {"ok": True}

    app.add_api_route("/capacity-probe", hold_request)

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        active = [asyncio.create_task(client.get("/capacity-probe")) for _ in range(2)]
        await asyncio.wait_for(both_entered.wait(), timeout=1)
        queued = asyncio.create_task(
            client.get("/capacity-probe", headers={"Origin": "http://localhost:5173"})
        )
        await asyncio.sleep(0.01)
        live = await client.get("/api/v2/live")
        overflow = await client.get(
            "/capacity-probe", headers={"Origin": "http://localhost:5173"}
        )
        release.set()
        responses = await asyncio.gather(*active, queued)

    assert [response.status_code for response in responses] == [200, 200, 200]
    assert live.status_code == 200
    assert overflow.status_code == 503
    assert overflow.headers["Retry-After"] == "1"
    assert overflow.headers["Access-Control-Allow-Origin"] == "http://localhost:5173"
    assert overflow.json()["code"] == "SERVICE_BUSY"
    assert overflow.json()["request_id"] == overflow.headers["X-Request-ID"]
