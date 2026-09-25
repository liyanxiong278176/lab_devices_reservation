from __future__ import annotations

import importlib.util
from pathlib import Path

import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations


def test_refresh_session_family_migration_revokes_legacy_rows_and_downgrades() -> None:
    migration_path = (
        Path(__file__).resolve().parents[1]
        / "migrations"
        / "versions"
        / "0023_refresh_session_families.py"
    )
    spec = importlib.util.spec_from_file_location(
        "refresh_session_family_migration",
        migration_path,
    )
    assert spec is not None and spec.loader is not None
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)

    engine = sa.create_engine("sqlite:///:memory:")
    with engine.begin() as connection:
        connection.execute(
            sa.text(
                "CREATE TABLE v2_refresh_session ("
                "id INTEGER PRIMARY KEY, token_id VARCHAR(64) NOT NULL, user_id INTEGER NOT NULL, "
                "expires_at DATETIME NOT NULL, revoked_at DATETIME NULL, "
                "replaced_by VARCHAR(64) NULL, created_at DATETIME NULL)"
            )
        )
        connection.execute(
            sa.text(
                "INSERT INTO v2_refresh_session "
                "(id, token_id, user_id, expires_at, revoked_at) VALUES "
                "(1, 'legacy-active', 1, '2099-01-01 00:00:00', NULL), "
                "(2, 'legacy-revoked', 1, '2099-01-01 00:00:00', '2025-01-01 00:00:00')"
            )
        )

        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()

        rows = connection.execute(
            sa.text("SELECT token_id, family_id, revoked_at FROM v2_refresh_session ORDER BY id")
        ).all()
        assert [(row.token_id, row.family_id) for row in rows] == [
            ("legacy-active", "legacy-active"),
            ("legacy-revoked", "legacy-revoked"),
        ]
        assert all(row.revoked_at is not None for row in rows)

        with Operations.context(MigrationContext.configure(connection)):
            migration.downgrade()

        assert "family_id" not in {
            column["name"] for column in sa.inspect(connection).get_columns("v2_refresh_session")
        }

    engine.dispose()
