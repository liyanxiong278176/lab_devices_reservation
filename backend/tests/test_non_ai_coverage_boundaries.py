from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from app.application import scope_access
from app.auth.security import Principal
from app.core import errors
from app.infrastructure.cache import invalidation
from app.infrastructure.db.models import OutboxTask
from fastapi import Request
from fastapi.exceptions import RequestValidationError
from sqlalchemy.exc import DBAPIError, OperationalError
from sqlalchemy.exc import TimeoutError as SQLAlchemyTimeoutError
from starlette.exceptions import HTTPException as StarletteHTTPException


def principal(*roles: str, college_id: int | None = 7, user_id: int = 11) -> Principal:
    return Principal(
        user_id=user_id,
        username="coverage-user",
        college_id=college_id,
        roles=roles,
        token_type="access",
        token_id="coverage-token",
    )


class ScalarSession:
    def __init__(self, *values: object) -> None:
        self.values = iter(values)
        self.statements = []

    async def scalar(self, statement):
        self.statements.append(statement)
        return next(self.values)


def request() -> Request:
    instance = Request(
        {
            "type": "http",
            "http_version": "1.1",
            "method": "GET",
            "scheme": "http",
            "path": "/test",
            "raw_path": b"/test",
            "query_string": b"",
            "headers": [],
            "client": ("127.0.0.1", 1234),
            "server": ("test", 80),
        }
    )
    instance.state.request_id = "request-123"
    return instance


@pytest.mark.asyncio
async def test_catalog_invalidation_outbox_and_best_effort_fast_path(monkeypatch) -> None:
    session = SimpleNamespace(add=Mock())
    invalidation.enqueue_catalog_cache_bump(session, None)
    session.add.assert_not_called()

    invalidation.enqueue_catalog_cache_bump(session, 7)
    task = session.add.call_args.args[0]
    assert isinstance(task, OutboxTask)
    assert task.task_type == "CACHE_BUMP"
    assert task.aggregate_key == "college:7"
    assert task.payload == {"scope": "college:7"}
    assert task.college_id == 7
    assert task.task_key.startswith("cache-bump:college:7:")
    assert task.execute_at.tzinfo is None

    assert await invalidation.sync_catalog_cache_bump(object(), None) is True

    cache = SimpleNamespace(bump_version=AsyncMock())
    monkeypatch.setattr(invalidation, "get_redis_for_app", lambda _app: object())
    monkeypatch.setattr(invalidation, "get_redis_circuit", lambda _app: object())
    monkeypatch.setattr(invalidation, "CacheService", lambda *_args: cache)
    app = SimpleNamespace(state=SimpleNamespace(settings=object(), metrics=None))

    assert await invalidation.sync_catalog_cache_bump(app, 7) is True
    cache.bump_version.assert_awaited_once_with("college:7")

    cache.bump_version.side_effect = RuntimeError("redis unavailable")
    assert await invalidation.sync_catalog_cache_bump(app, 7) is False


@pytest.mark.asyncio
async def test_manageable_device_queries_and_scope_permissions_cover_roles_and_scopes(
    monkeypatch,
) -> None:
    system_admin = principal("SYS_ADMIN", college_id=None)
    manager = principal("LAB_ADMIN")
    student = principal("STUDENT")

    sys_query = scope_access.manageable_device_ids_statement(system_admin)
    assert "device.id" in str(sys_query)
    denied_query = scope_access.manageable_device_ids_statement(student)
    assert "false" in str(denied_query).lower()
    manager_query = scope_access.manageable_device_ids_statement(manager)
    assert "device.college_id" in str(manager_query)

    assert await scope_access.can_manage_scope(ScalarSession(), system_admin, "GLOBAL", 0) is True
    assert await scope_access.can_manage_scope(ScalarSession(), system_admin, "GLOBAL", 1) is False
    assert await scope_access.can_manage_scope(ScalarSession(), manager, "GLOBAL", 0) is False

    sys_session = ScalarSession(1, 2, 3)
    assert await scope_access.can_manage_scope(sys_session, system_admin, "COLLEGE", 1) is True
    assert await scope_access.can_manage_scope(sys_session, system_admin, "LAB", 2) is True
    assert await scope_access.can_manage_scope(sys_session, system_admin, "DEVICE", 3) is True
    assert await scope_access.can_manage_scope(ScalarSession(), system_admin, "UNKNOWN", 1) is False

    assert await scope_access.can_manage_scope(ScalarSession(), student, "DEVICE", 1) is False
    assert await scope_access.can_manage_scope(
        ScalarSession(7), manager, "COLLEGE", 7
    ) is True
    assert await scope_access.can_manage_scope(
        ScalarSession(None), manager, "COLLEGE", 7
    ) is False
    assert await scope_access.can_manage_scope(ScalarSession(1), manager, "LAB", 4) is True
    assert await scope_access.can_manage_scope(ScalarSession(1), manager, "DEVICE", 5) is True
    assert await scope_access.can_manage_scope(ScalarSession(), manager, "OTHER", 8) is False

    assert scope_access.manageable_scope_condition(manager) is not False
    assert scope_access.manageable_scope_condition(system_admin) is None
    assert scope_access.manageable_scope_condition(student) is False

    monkeypatch.setattr(scope_access, "college_scope", lambda _principal: None)
    assert await scope_access.can_manage_scope(
        ScalarSession(), principal("LAB_ADMIN", college_id=None), "DEVICE", 1
    ) is False
    assert "false" in str(
        scope_access.manageable_device_ids_statement(principal("LAB_ADMIN", college_id=None))
    ).lower()
    assert scope_access.manageable_scope_condition(principal("LAB_ADMIN", college_id=None)) is False


@pytest.mark.asyncio
async def test_error_handlers_preserve_request_context_and_classify_dependency_failures() -> None:
    req = request()
    api_response = await errors.api_error_handler(
        req,
        errors.ApiError("CONFLICT", "reserved", 409, {"slot": "2026-09-28"}, {"X-Custom": "v"}),
    )
    assert api_response.status_code == 409
    assert api_response.headers["x-custom"] == "v"
    assert json.loads(api_response.body) == {
        "code": "CONFLICT",
        "message": "reserved",
        "data": {"slot": "2026-09-28"},
        "request_id": "request-123",
    }

    pool_full = await errors.unhandled_error_handler(req, SQLAlchemyTimeoutError("pool full"))
    assert pool_full.status_code == 503
    assert pool_full.headers["retry-after"] == "1"
    assert json.loads(pool_full.body)["code"] == "SERVICE_BUSY"

    for exc in (TimeoutError("timed out"), ConnectionError("redis down"), OSError("socket")):
        response = await errors.unhandled_error_handler(req, exc)
        assert response.status_code == 503
        assert json.loads(response.body)["code"] == "DEPENDENCY_UNAVAILABLE"
        assert response.headers["x-request-id"] == "request-123"

    operational = await errors.unhandled_error_handler(
        req, OperationalError("SELECT 1", {}, RuntimeError("connect failed"))
    )
    assert operational.status_code == 503

    invalidated = DBAPIError.instance(
        "SELECT 1", {}, RuntimeError("lost"), Exception, connection_invalidated=True
    )
    assert (await errors.unhandled_error_handler(req, invalidated)).status_code == 503

    ordinary_db_error = DBAPIError.instance(
        "SELECT 1", {}, RuntimeError("bad query"), Exception, connection_invalidated=False
    )
    internal = await errors.unhandled_error_handler(req, ordinary_db_error)
    assert internal.status_code == 500
    assert json.loads(internal.body)["code"] == "INTERNAL_ERROR"


@pytest.mark.asyncio
async def test_http_and_validation_error_handlers_cover_mapping_and_plain_details() -> None:
    req = request()
    mapped = await errors.http_error_handler(
        req,
        StarletteHTTPException(404, detail={"code": "MISSING", "message": "not found"}),
    )
    assert mapped.status_code == 404
    assert json.loads(mapped.body)["code"] == "MISSING"
    assert json.loads(mapped.body)["request_id"] == "request-123"

    plain = await errors.http_error_handler(req, StarletteHTTPException(403, detail="forbidden"))
    assert json.loads(plain.body)["code"] == "HTTP_ERROR"
    assert json.loads(plain.body)["message"] == "forbidden"

    validation = await errors.validation_error_handler(
        req,
        RequestValidationError(
            [{"loc": ("query", "page"), "msg": "invalid", "type": "int_parsing"}]
        ),
    )
    body = json.loads(validation.body)
    assert validation.status_code == 422
    assert body["code"] == "VALIDATION_ERROR"
    assert body["data"]["errors"][0]["loc"] == ["query", "page"]
