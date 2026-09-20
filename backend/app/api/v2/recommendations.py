from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v2.schemas import RecommendationData
from app.application.recommendations import RecommendationService
from app.auth.security import Principal, get_current_principal
from app.common.response import ApiResponse
from app.infrastructure.cache.cache import CacheService
from app.infrastructure.cache.rate_limit import enforce_authenticated_rate_limit
from app.infrastructure.cache.redis import get_redis, get_redis_circuit
from app.infrastructure.db.session import get_db

router = APIRouter(dependencies=[Depends(enforce_authenticated_rate_limit)])


@router.get(
    "/recommendations",
    response_model=ApiResponse[list[RecommendationData]],
)
async def recommendations(
    request: Request,
    limit: int = Query(default=10, ge=1, le=50),
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
) -> ApiResponse[list[RecommendationData]]:
    settings = request.app.state.settings
    cache = CacheService(
        redis,
        settings,
        getattr(request.app.state, "metrics", None),
        get_redis_circuit(request.app),
    )
    data = await RecommendationService(session, principal, cache=cache).recommend(
        limit,
        cache_ttl_seconds=settings.recommend_cache_ttl_seconds,
    )
    return ApiResponse.ok(data)
