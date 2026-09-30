"""Opt-in MySQL verification for the maintenance retest schema revision."""

from __future__ import annotations

import importlib
import os

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from app.core.settings import Settings
from app.infrastructure.db.session import build_engine
from sqlalchemy.exc import IntegrityError


def _exercise_retest_revision(connection) -> None:
    connection.exec_driver_sql(
        "CREATE TEMPORARY TABLE v2_device_maintenance_record ("
        "id BIGINT NOT NULL PRIMARY KEY, "
        "plan_id BIGINT NOT NULL, "
        "cycle_due_date DATE NOT NULL, "
        "CONSTRAINT uk_v2_maintenance_record_cycle "
        "UNIQUE (plan_id, cycle_due_date)"
        ")"
    )
    revision = importlib.import_module("migrations.versions.0028_maintenance_retests")
    try:
        with Operations.context(MigrationContext.configure(connection)):
            revision.upgrade()

        connection.exec_driver_sql(
            "INSERT INTO v2_device_maintenance_record (id, plan_id, cycle_due_date) "
            "VALUES (1, 7, '2026-09-26'), (2, 7, '2026-09-26')"
        )
        count = connection.exec_driver_sql(
            "SELECT COUNT(*) FROM v2_device_maintenance_record "
            "WHERE plan_id = 7 AND cycle_due_date = '2026-09-26'"
        ).scalar_one()
        assert count == 2

        with Operations.context(MigrationContext.configure(connection)):
            with pytest.raises(RuntimeError, match="multiple attempts"):
                revision.downgrade()

        connection.exec_driver_sql("DELETE FROM v2_device_maintenance_record WHERE id = 2")
        with Operations.context(MigrationContext.configure(connection)):
            revision.downgrade()

        with pytest.raises(IntegrityError):
            connection.exec_driver_sql(
                "INSERT INTO v2_device_maintenance_record (id, plan_id, cycle_due_date) "
                "VALUES (3, 7, '2026-09-26')"
            )
    finally:
        connection.rollback()
        connection.exec_driver_sql("DROP TEMPORARY TABLE IF EXISTS v2_device_maintenance_record")


@pytest.mark.asyncio
async def test_mysql_maintenance_retest_revision_upgrade_and_safe_downgrade() -> None:
    if os.getenv("LAB_RUN_MYSQL_INTEGRATION") != "1":
        pytest.skip("set LAB_RUN_MYSQL_INTEGRATION=1 to run against the configured MySQL")

    settings = Settings()
    if settings.mysql_dsn.startswith("sqlite"):
        pytest.skip("this test verifies MySQL ALTER TABLE and unique-index behavior")

    engine = build_engine(settings)
    try:
        async with engine.connect() as connection:
            await connection.run_sync(_exercise_retest_revision)
    finally:
        await engine.dispose()
