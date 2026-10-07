"""Run with LAB_TEST_CATALOG_MYSQL_DSN pointing to an empty, migrated test schema."""

from __future__ import annotations

import asyncio
import os

import pytest
from app.infrastructure.db.catalog_bootstrap import seed_initial_catalog
from app.infrastructure.db.models import Device, DeviceMaintenancePlan, Role, User
from app.infrastructure.db.session import build_session_factory
from sqlalchemy import func, select
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine


async def test_mysql_deployment_catalog_lock_and_repeatability():
    dsn = os.getenv("LAB_TEST_CATALOG_MYSQL_DSN")
    if not dsn:
        pytest.skip("set LAB_TEST_CATALOG_MYSQL_DSN to an isolated migrated test schema")
    url = make_url(dsn)
    assert url.get_backend_name() == "mysql"
    assert url.database and url.database.startswith("lab_test_catalog_")
    engine = create_async_engine(dsn, pool_pre_ping=True, isolation_level="READ COMMITTED")
    factory = build_session_factory(engine)
    try:
        async with factory() as session:
            assert await session.scalar(select(func.count()).select_from(Device)) == 0
            role = await session.scalar(select(Role).where(Role.role_code == "SYS_ADMIN"))
            assert role is not None, "run Alembic migrations on the isolated schema first"
            session.add(
                User(
                    username="catalog-test-admin", password_hash="test-only", status=1, roles=[role]
                )
            )
            await session.commit()
        runs = await asyncio.gather(seed_initial_catalog(engine), seed_initial_catalog(engine))
        assert sorted(run["devices"] for run in runs) == [0, 18]
        assert sorted(run["plans"] for run in runs) == [0, 18]
        async with factory() as session:
            assert await session.scalar(select(func.count()).select_from(Device)) == 18
            assert (
                await session.scalar(select(func.count()).select_from(DeviceMaintenancePlan)) == 18
            )
            codes = list((await session.scalars(select(Device.asset_code))).all())
            assert len(set(codes)) == 18
            plan = await session.scalar(select(DeviceMaintenancePlan))
            plan_id = plan.id
            plan.title, plan.active = "operator-edited-plan", False
            await session.commit()
        repeated = await seed_initial_catalog(engine)
        assert repeated["devices"] == repeated["plans"] == 0
        async with factory() as session:
            plan = await session.get(DeviceMaintenancePlan, plan_id)
            assert plan.title == "operator-edited-plan" and plan.active is False
    finally:
        await engine.dispose()
