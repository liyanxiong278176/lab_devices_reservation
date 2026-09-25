import asyncio

import pytest
from app.core.settings import Settings
from app.main import create_app
from fastapi.testclient import TestClient
from httpx import ASGITransport, AsyncClient
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
    assert (
        client.get(
            "/api/v2/metrics",
            headers={"Authorization": f"Bearer {token}"},
        ).status_code
        == 200
    )


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

    assert 'path="__unmatched__"' in metrics
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
    assert len(registry.render_prometheus().splitlines()) == 4


@pytest.mark.asyncio
async def test_overload_is_rejected_before_business_handler_and_live_stays_available() -> None:
    app = create_app(
        Settings(
            environment="test",
            cors_origins=["http://localhost:5173"],
            db_pool_size=1,
            db_max_overflow=1,
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
        overflow = asyncio.create_task(
            client.get("/capacity-probe", headers={"Origin": "http://localhost:5173"})
        )
        await asyncio.sleep(0.01)
        live = await client.get("/api/v2/live")
        release.set()
        responses = await asyncio.gather(*active)
        overflow_response = await overflow

    assert [response.status_code for response in responses] == [200, 200]
    assert live.status_code == 200
    assert overflow_response.status_code == 503
    assert overflow_response.headers["Retry-After"] == "1"
    assert overflow_response.headers["Access-Control-Allow-Origin"] == "http://localhost:5173"
    assert overflow_response.json()["code"] == "SERVICE_BUSY"
    assert overflow_response.json()["request_id"] == overflow_response.headers["X-Request-ID"]
