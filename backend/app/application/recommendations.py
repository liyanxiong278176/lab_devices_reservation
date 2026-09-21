from __future__ import annotations

import json
from collections import Counter
from datetime import UTC, datetime, timedelta

from redis.asyncio import Redis
from redis.exceptions import RedisError
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.v2.schemas import RecommendationData
from app.auth.security import Principal, college_scope
from app.infrastructure.cache.cache import CacheService
from app.infrastructure.db.models import College, Device, Lab, Reservation

ACTIVE_STATUSES = ("PENDING", "APPROVED", "IN_USE")
PREFERENCE_STATUSES = ("PENDING", "APPROVED", "IN_USE", "COMPLETED")
EXCLUDED_STATUSES = ("CANCELLED", "REJECTED", "NO_SHOW", "VIOLATED")

# The weights intentionally remain server-side. Recommendation results are
# an explanation aid, never an authorization decision.
WEIGHTS = {
    "category": 0.40,
    "lab": 0.20,
    "popularity": 0.25,
    "tags": 0.10,
    "active_penalty": 0.30,
}
MAX_CACHE_SIZE = 50


class RecommendationService:
    def __init__(
        self,
        session: AsyncSession,
        principal: Principal,
        redis: Redis | None = None,
        cache: CacheService | None = None,
    ):
        self.session = session
        self.principal = principal
        self.redis = redis
        self.cache = cache

    async def recommend(
        self,
        limit: int = 10,
        *,
        cache_ttl_seconds: int = 300,
    ) -> list[RecommendationData]:
        limit = max(1, min(limit, MAX_CACHE_SIZE))
        if self.cache is not None and not self.principal.is_system_admin:
            scope = college_scope(self.principal)
            if scope is not None:
                try:
                    scope_key = f"college:{scope}"
                    version = await self.cache.version(scope_key)
                    viewer = "manager" if self.principal.is_lab_admin else "member"
                    cache_key = (
                        f"lab:v2:recommendations:{scope_key}:v{version}:"
                        f"{viewer}:user:{self.principal.user_id}"
                    )

                    async def load() -> list[dict[str, object]]:
                        return [item.model_dump(mode="json") for item in await self._compute()]

                    raw = await self.cache.get_or_set_json(
                        cache_key,
                        load,
                        ttl_seconds=cache_ttl_seconds,
                    )
                    if isinstance(raw, list):
                        return [RecommendationData.model_validate(item) for item in raw][:limit]
                except Exception:
                    # Recommendations are an optimization; always fall back
                    # to the authoritative calculation on cache failure.
                    pass
        cache_key = self._cache_key()
        cached = await self._read_cache(cache_key)
        if cached is not None:
            return cached[:limit]

        ranked = await self._compute()
        await self._write_cache(cache_key, ranked, cache_ttl_seconds)
        return ranked[:limit]

    def _cache_key(self) -> str:
        scope = "all" if self.principal.is_system_admin else str(self.principal.college_id)
        return f"lab:v2:recommendations:{scope}:user:{self.principal.user_id}"

    async def _read_cache(self, key: str) -> list[RecommendationData] | None:
        if self.redis is None:
            return None
        try:
            value = await self.redis.get(key)
            if not value:
                return None
            raw = json.loads(value)
            if not isinstance(raw, list):
                return None
            return [RecommendationData.model_validate(item) for item in raw]
        except (RedisError, OSError, TimeoutError, ValueError, TypeError):
            return None

    async def _write_cache(
        self,
        key: str,
        values: list[RecommendationData],
        ttl_seconds: int,
    ) -> None:
        if self.redis is None:
            return
        try:
            payload = json.dumps(
                [item.model_dump(mode="json") for item in values],
                ensure_ascii=False,
            )
            await self.redis.set(key, payload, ex=max(30, ttl_seconds))
        except (RedisError, OSError, TimeoutError, TypeError):
            # Recommendation cache is best-effort; the database remains the
            # source of truth and a cache outage must not affect reservations.
            return

    async def _compute(self) -> list[RecommendationData]:
        scope = college_scope(self.principal)
        candidates_stmt = (
            select(Device)
            .options(selectinload(Device.category), selectinload(Device.lab))
            .where(Device.status == "IDLE")
        )
        if scope is None:
            pass
        elif self.principal.is_lab_admin:
            candidates_stmt = (
                candidates_stmt.outerjoin(Lab, Lab.id == Device.lab_id)
                .join(College, College.id == Device.college_id)
                .where(
                    Device.college_id == scope,
                    or_(
                        Lab.manager_id == self.principal.user_id,
                        College.manager_id == self.principal.user_id,
                    ),
                )
            )
        else:
            candidates_stmt = candidates_stmt.where(Device.college_id == scope)

        candidates = list(
            (await self.session.scalars(candidates_stmt.order_by(Device.id))).unique().all()
        )
        if not candidates:
            return []

        candidate_ids = [device.id for device in candidates]
        history_conditions = [
            Reservation.user_id == self.principal.user_id,
            Reservation.status.in_(PREFERENCE_STATUSES),
        ]
        if scope is not None:
            history_conditions.append(Reservation.college_id == scope)
        history_device_ids = list(
            (
                await self.session.scalars(select(Reservation.device_id).where(*history_conditions))
            ).all()
        )
        history_devices: list[Device] = []
        if history_device_ids:
            history_devices = list(
                (
                    await self.session.scalars(
                        select(Device)
                        .options(selectinload(Device.category), selectinload(Device.lab))
                        .where(Device.id.in_(set(history_device_ids)))
                    )
                )
                .unique()
                .all()
            )

        category_counts: Counter[int] = Counter()
        lab_counts: Counter[int] = Counter()
        tag_frequency: Counter[str] = Counter()
        for device in history_devices:
            if device.category_id is not None:
                category_counts[device.category_id] += 1
            if device.lab_id is not None:
                lab_counts[device.lab_id] += 1
            for tag in device.tags or []:
                if isinstance(tag, str) and tag.strip():
                    tag_frequency[tag.strip()] += 1
        total_history = len(history_devices)
        preferred_tags = set(tag_frequency)

        since = datetime.now(UTC).replace(tzinfo=None) - timedelta(days=30)
        popularity_conditions = [
            Reservation.device_id.in_(candidate_ids),
            Reservation.created_at >= since,
            Reservation.status.not_in(EXCLUDED_STATUSES),
        ]
        if scope is not None:
            popularity_conditions.append(Reservation.college_id == scope)
        popularity_rows = (
            await self.session.execute(
                select(Reservation.device_id, func.count(Reservation.id))
                .where(*popularity_conditions)
                .group_by(Reservation.device_id)
            )
        ).all()
        popularity = {int(device_id): int(count) for device_id, count in popularity_rows}
        max_popularity = max(popularity.values(), default=0)

        active_conditions = [
            Reservation.user_id == self.principal.user_id,
            Reservation.device_id.in_(candidate_ids),
            Reservation.status.in_(ACTIVE_STATUSES),
        ]
        if scope is not None:
            active_conditions.append(Reservation.college_id == scope)
        active_device_ids = set(
            (
                await self.session.scalars(select(Reservation.device_id).where(*active_conditions))
            ).all()
        )

        ranked: list[RecommendationData] = []
        for device in candidates:
            category_ratio = (
                category_counts[device.category_id] / total_history
                if total_history and device.category_id is not None
                else 0.0
            )
            lab_ratio = (
                lab_counts[device.lab_id] / total_history
                if total_history and device.lab_id is not None
                else 0.0
            )
            device_tags = {
                tag.strip() for tag in device.tags or [] if isinstance(tag, str) and tag.strip()
            }
            tag_ratio = (
                len(device_tags & preferred_tags) / len(preferred_tags) if preferred_tags else 0.0
            )
            popularity_ratio = (
                popularity.get(device.id, 0) / max_popularity if max_popularity else 0.0
            )
            category_contribution = WEIGHTS["category"] * category_ratio
            lab_contribution = WEIGHTS["lab"] * lab_ratio
            popularity_contribution = WEIGHTS["popularity"] * popularity_ratio
            tag_contribution = WEIGHTS["tags"] * tag_ratio
            score = (
                category_contribution
                + lab_contribution
                + popularity_contribution
                + tag_contribution
                - (WEIGHTS["active_penalty"] if device.id in active_device_ids else 0.0)
            )
            category_name = device.category.name if device.category else None
            lab_name = device.lab.name if device.lab else None
            ranked.append(
                RecommendationData(
                    device_id=device.id,
                    name=device.name,
                    category_id=device.category_id,
                    category_name=category_name,
                    lab_id=device.lab_id,
                    lab_name=lab_name,
                    score=round(score, 4),
                    reason=self._reason(
                        category_contribution,
                        lab_contribution,
                        tag_contribution,
                        popularity_contribution,
                        category_name,
                        lab_name,
                    ),
                    brand=device.brand,
                    model=device.model,
                    status=device.status,
                )
            )
        ranked.sort(key=lambda item: (-item.score, item.device_id))
        return ranked[:MAX_CACHE_SIZE]

    @staticmethod
    def _reason(
        category: float,
        lab: float,
        tags: float,
        popularity: float,
        category_name: str | None,
        lab_name: str | None,
    ) -> str:
        best = max(category, lab, tags, popularity)
        if category >= best - 0.01 and category > 0:
            return f"因你常约【{category_name or '该类目'}】设备"
        if lab >= best - 0.01 and lab > 0:
            return f"因你常用【{lab_name or '该实验室'}】"
        if tags >= best - 0.01 and tags > 0:
            return "标签匹配你的偏好"
        return "近30天热门设备"
