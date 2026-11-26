"""The Alembic migrations must apply, roll back, and match the ORM models exactly."""

from __future__ import annotations

import os
import subprocess
import sys

import pytest

from tests.conftest import BACKEND_DIR


def alembic(db_url: str, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=BACKEND_DIR,
        env={**os.environ, "DATABASE_URL": db_url},
        capture_output=True,
        text=True,
    )


def test_models_and_migrations_are_in_sync(migrated_db: str) -> None:
    result = alembic(migrated_db, "check")
    assert result.returncode == 0, result.stderr


def test_downgrade_and_upgrade_roundtrip(
    database_url: str,
    tmp_path_factory: pytest.TempPathFactory,
) -> None:
    if os.environ.get("TEST_DATABASE_URL"):
        pytest.skip("Roundtrip migration test requires a disposable PostgreSQL server.")

    if sys.platform == "win32":
        pytest.skip("pgserver is not supported by this Windows test configuration.")

    import pgserver

    if os.environ.get("TEST_DATABASE_URL"):
        return  # do not run destructive downgrade on a shared database
    server = pgserver.get_server(tmp_path_factory.mktemp("pg2"), cleanup_mode="stop")
    url = server.get_uri().replace("postgresql://", "postgresql+psycopg://")
    assert alembic(url, "upgrade", "head").returncode == 0
    assert "ix_pages_fts" in server.psql("select indexname from pg_indexes where tablename='pages';")
    assert "ix_page_embeddings_hnsw" in server.psql(
        "select indexname from pg_indexes where tablename='page_embeddings';"
    )
    assert alembic(url, "downgrade", "base").returncode == 0
    assert "documents" not in server.psql("select tablename from pg_tables where schemaname='public';")
    assert alembic(url, "upgrade", "head").returncode == 0
