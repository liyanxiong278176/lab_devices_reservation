from app.core.settings import Settings
from app.main import create_app
from fastapi.testclient import TestClient


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
        "data": {
            "service": "Laboratory Reservation API",
            "version": "2.0.0",
            "environment": "test",
            "checks": {"configuration": "ok"},
        },
        "request_id": response.headers["X-Request-ID"],
    }


def test_client_request_id_is_preserved() -> None:
    client = TestClient(create_app(Settings(environment="test", cors_origins=[])))

    response = client.get("/api/v2/ready", headers={"X-Request-ID": "req-test-001"})

    assert response.status_code == 200
    assert response.headers["X-Request-ID"] == "req-test-001"
    assert response.json()["request_id"] == "req-test-001"


def test_business_errors_keep_their_http_status_and_envelope() -> None:
    client = TestClient(create_app(Settings(environment="test", cors_origins=[])))

    response = client.get("/api/v2/devices")

    assert response.status_code == 401
    assert response.json()["code"] == "AUTH_REQUIRED"
    assert response.json()["data"] is None
