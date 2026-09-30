from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from app.api.v2.schemas import RecommendationData
from app.application.recommendations import RecommendationService
from app.auth.security import Principal
from app.infrastructure.db.models import Device, DeviceCategory, Reservation
from redis.exceptions import RedisError


def _principal(user, *roles: str) -> Principal:
    permissions = ("device:read",) if "SYS_ADMIN" not in roles else ()
    return Principal(
        user_id=user.id,
        username=user.username,
        college_id=user.college_id,
        roles=roles,
        token_type="access",
        token_id="recommendation-coverage",
        permissions=permissions,
    )


def _recommendation(device_id: int, name: str = "设备") -> RecommendationData:
    return RecommendationData(
        device_id=device_id,
        name=name,
        score=0.5,
        reason="近30天热门设备",
        status="IDLE",
    )


class FakeCache:
    def __init__(self, result=None, error: Exception | None = None) -> None:
        self.result = result
        self.error = error
        self.keys: list[str] = []

    async def version(self, _scope: str) -> int:
        return 3

    async def get_or_set_json(self, key: str, loader, *, ttl_seconds: int):
        self.keys.append(key)
        if self.error is not None:
            raise self.error
        if self.result is not None:
            return self.result
        return await loader()


@pytest.mark.asyncio
async def test_recommendation_cache_hit_and_failure_fallback(seeded, monkeypatch) -> None:
    factory, _, _, student, _, _, device, _ = seeded
    async with factory() as session:
        cached_item = _recommendation(device.id, "cached")
        cache = FakeCache(result=[cached_item.model_dump(mode="json")])
        service = RecommendationService(session, _principal(student, "STUDENT"), cache=cache)
        compute = AsyncMock(return_value=[])
        monkeypatch.setattr(service, "_compute", compute)
        result = await service.recommend(limit=10, cache_ttl_seconds=17)
        assert [item.name for item in result] == ["cached"]
        assert "college:" in cache.keys[0]
        compute.assert_not_awaited()

        failing_cache = FakeCache(error=RuntimeError("version store offline"))
        fallback = RecommendationService(
            session, _principal(student, "STUDENT"), cache=failing_cache
        )
        computed = [_recommendation(device.id)]
        monkeypatch.setattr(fallback, "_compute", AsyncMock(return_value=computed))
        assert await fallback.recommend(limit=0) == computed
        assert len(failing_cache.keys) == 1


@pytest.mark.asyncio
async def test_recommendation_invalid_new_cache_result_falls_back_to_redis(
    seeded, monkeypatch
) -> None:
    factory, _, _, student, _, _, device, _ = seeded
    async with factory() as session:
        redis = SimpleNamespace(get=AsyncMock(return_value=None), set=AsyncMock())
        service = RecommendationService(
            session,
            _principal(student, "STUDENT"),
            redis=redis,
            cache=FakeCache(result={"not": "a list"}),
        )
        computed = [_recommendation(device.id)]
        compute = AsyncMock(return_value=computed)
        monkeypatch.setattr(service, "_compute", compute)
        assert await service.recommend(limit=1) == computed
        compute.assert_awaited_once()
        redis.set.assert_awaited_once()
        assert redis.set.await_args.kwargs["ex"] == 300


@pytest.mark.asyncio
async def test_recommendation_without_tenant_scope_skips_scoped_cache_and_uses_redis(
    seeded,
) -> None:
    factory, _, _, _, _, admin_user, *_ = seeded
    async with factory() as session:
        item = _recommendation(7, "redis cached")
        redis = SimpleNamespace(
            get=AsyncMock(return_value=json.dumps([item.model_dump(mode="json")])),
            set=AsyncMock(),
        )
        cache = FakeCache(error=AssertionError("system admins bypass the tenant cache"))
        principal = _principal(admin_user, "SYS_ADMIN")
        service = RecommendationService(session, principal, redis=redis, cache=cache)
        assert [result.name for result in await service.recommend()] == ["redis cached"]
        assert cache.keys == []
        redis.set.assert_not_awaited()


@pytest.mark.asyncio
async def test_recommendation_global_scope_handles_history_without_category_or_lab(seeded) -> None:
    factory, college, _, _, _, admin_user, _, _ = seeded
    async with factory() as session:
        history = Device(
            name="管理员历史设备",
            college_id=college.id,
            lab_id=None,
            category_id=None,
            status="RETIRED",
            need_approval=False,
            tags=None,
        )
        session.add(history)
        await session.flush()
        session.add(
            Reservation(
                college_id=college.id,
                user_id=admin_user.id,
                device_id=history.id,
                start_date=date.today() - timedelta(days=3),
                end_date=date.today() - timedelta(days=3),
                status="COMPLETED",
                created_at=datetime.now(UTC).replace(tzinfo=None),
            )
        )
        await session.commit()

        results = await RecommendationService(
            session, _principal(admin_user, "SYS_ADMIN")
        )._compute()
        assert results
        assert all(result.status == "IDLE" for result in results)


@pytest.mark.asyncio
async def test_recommendation_lab_admin_scope_and_user_without_history(seeded) -> None:
    factory, _, _, student, _, manager, device, _ = seeded
    async with factory() as session:
        student_results = await RecommendationService(
            session, _principal(student, "STUDENT")
        )._compute()
        assert any(result.device_id == device.id for result in student_results)

        manager_results = await RecommendationService(
            session, _principal(manager, "LAB_ADMIN")
        )._compute()
        assert any(result.device_id == device.id for result in manager_results)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, None),
        (b"", None),
        (b"{}", None),
        (b"not-json", None),
        (b"[{\"device_id\": \"bad\"}]", None),
        (b"[{\"device_id\": 7, \"name\": \"cached\", \"score\": 0.2, "
         b"\"reason\": \"matched\", \"status\": \"IDLE\"}]", "cached"),
    ],
)
async def test_recommendation_redis_read_handles_empty_malformed_and_valid_values(
    value, expected
) -> None:
    redis = SimpleNamespace(get=AsyncMock(return_value=value))
    service = RecommendationService(None, None, redis=redis)  # type: ignore[arg-type]
    if value is None:
        service.redis = None
        assert await service._read_cache("key") is None
        return
    result = await service._read_cache("key")
    assert (result[0].name if result else None) == expected


@pytest.mark.asyncio
async def test_recommendation_redis_failures_are_best_effort() -> None:
    redis = SimpleNamespace(get=AsyncMock(side_effect=RedisError("offline")), set=AsyncMock())
    service = RecommendationService(None, None, redis=redis)  # type: ignore[arg-type]
    assert await service._read_cache("key") is None
    await service._write_cache("key", [_recommendation(1)], ttl_seconds=1)
    redis.set.assert_awaited_once()
    assert redis.set.await_args.kwargs["ex"] == 30

    redis.set.side_effect = RedisError("offline")
    await service._write_cache("key", [_recommendation(2)], ttl_seconds=60)


@pytest.mark.asyncio
async def test_recommendation_skips_empty_candidate_set_and_global_admin_uses_global_key(
    seeded, monkeypatch
) -> None:
    factory, _, _, student, _, admin_user, device, _ = seeded
    async with factory() as session:
        stored = await session.get(Device, device.id)
        assert stored is not None
        stored.status = "MAINTENANCE"
        await session.commit()
        empty = await RecommendationService(
            session, _principal(student, "STUDENT")
        )._compute()
        assert empty == []

        redis = SimpleNamespace(get=AsyncMock(return_value=None), set=AsyncMock())
        cache = FakeCache(error=AssertionError("system admins bypass tenant cache"))
        admin = RecommendationService(
            session,
            _principal(admin_user, "SYS_ADMIN"),
            redis=redis,
            cache=cache,
        )
        assert admin._cache_key() == f"lab:v2:recommendations:all:user:{admin_user.id}"
        computed = [_recommendation(1)]
        monkeypatch.setattr(admin, "_compute", AsyncMock(return_value=computed))
        assert await admin.recommend(limit=500) == computed
        assert cache.keys == []
        assert redis.set.await_args.args[0] == admin._cache_key()


@pytest.mark.asyncio
async def test_recommendation_scores_history_tags_popularity_and_active_use(seeded) -> None:
    factory, college, _, student, _, _, device, _ = seeded
    async with factory() as session:
        category = DeviceCategory(name="光谱仪")
        session.add(category)
        await session.flush()
        original = await session.get(Device, device.id)
        assert original is not None
        original.category_id = category.id
        original.tags = ["光谱", "", 9]

        second = Device(
            name="同类候选设备",
            college_id=college.id,
            lab_id=original.lab_id,
            category_id=category.id,
            status="IDLE",
            need_approval=False,
            tags=["光谱"],
        )
        third = Device(
            name="无偏好候选设备",
            college_id=college.id,
            status="IDLE",
            need_approval=False,
            tags=["  "],
        )
        history = Device(
            name="历史设备",
            college_id=college.id,
            lab_id=original.lab_id,
            category_id=category.id,
            status="RETIRED",
            need_approval=False,
            tags=["光谱", " 光谱 ", None],
        )
        session.add_all([second, third, history])
        await session.flush()
        now = datetime.now(UTC).replace(tzinfo=None)
        session.add_all(
            [
                Reservation(
                    college_id=college.id,
                    user_id=student.id,
                    device_id=history.id,
                    start_date=date.today() - timedelta(days=2),
                    end_date=date.today() - timedelta(days=2),
                    status="COMPLETED",
                    created_at=now - timedelta(days=2),
                ),
                Reservation(
                    college_id=college.id,
                    user_id=student.id,
                    device_id=original.id,
                    start_date=date.today() - timedelta(days=1),
                    end_date=date.today() - timedelta(days=1),
                    status="COMPLETED",
                    created_at=now - timedelta(days=1),
                ),
                Reservation(
                    college_id=college.id,
                    user_id=student.id,
                    device_id=second.id,
                    start_date=date.today() + timedelta(days=1),
                    end_date=date.today() + timedelta(days=1),
                    status="PENDING",
                    created_at=now,
                ),
            ]
        )
        await session.commit()

        results = await RecommendationService(
            session, _principal(student, "STUDENT")
        ).recommend()
        by_id = {item.device_id: item for item in results}
        assert set(by_id) == {original.id, second.id, third.id}
        assert by_id[original.id].score > by_id[second.id].score
        assert by_id[second.id].score > by_id[third.id].score
        assert by_id[original.id].reason.startswith("因你常约")
        assert by_id[third.id].reason == "近30天热门设备"


def test_recommendation_reason_explains_each_positive_signal() -> None:
    reason = RecommendationService._reason
    assert reason(0.4, 0.1, 0.1, 0.1, None, "实验室") == "因你常约【该类目】设备"
    assert reason(0.0, 0.3, 0.1, 0.1, "类目", None) == "因你常用【该实验室】"
    assert reason(0.0, 0.0, 0.4, 0.1, None, None) == "标签匹配你的偏好"
    assert reason(0.0, 0.0, 0.0, 0.0, None, None) == "近30天热门设备"
