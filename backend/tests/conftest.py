"""Shared test fixtures.

* A real PostgreSQL (with pgvector) is used: either TEST_DATABASE_URL (e.g. the docker compose database)
  or a throw-away server started by the `pgserver` package.
* Celery runs in eager mode, so the whole pipeline executes inside the test process.
"""

from __future__ import annotations

import os
import random
import shutil
import subprocess
import sys
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest

from app.core.security import hash_password

os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("CELERY_EAGER", "true")
os.environ.setdefault("LOG_LEVEL", "WARNING")
os.environ.setdefault("LOG_JSON", "false")
os.environ.setdefault("JWT_SECRET", "unit-test-only-secret-not-for-real-use-0123456789")

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import text  # noqa: E402

from app.core.config import get_settings  # noqa: E402
from app.db.base import get_engine, reset_engine, session_scope  # noqa: E402
from app.services import users  # noqa: E402
from app.services.runtime import reset_runtime  # noqa: E402

BACKEND_DIR = Path(__file__).resolve().parents[1]


def _use_settings(**env: str) -> None:
    for key, value in env.items():
        os.environ[key] = value
    get_settings.cache_clear()
    reset_engine()
    reset_runtime()


@pytest.fixture(scope="session")
def database_url(tmp_path_factory: pytest.TempPathFactory) -> Iterator[str]:
    url = os.environ.get("TEST_DATABASE_URL")
    if url:
        # Safety: the tests TRUNCATE tables, so refuse anything that is not clearly a test database.
        name = url.rsplit("/", 1)[-1].split("?")[0]
        assert name.endswith("test"), (
            f"TEST_DATABASE_URL must point to a database whose name ends with 'test' (got '{name}')"
        )
        yield url
        return
    try:
        import pgserver
    except ImportError:  # pragma: no cover
        pytest.skip("Set TEST_DATABASE_URL or install pgserver to run database tests")
    server = pgserver.get_server(tmp_path_factory.mktemp("pg"), cleanup_mode="stop")  # type: ignore[attr-defined]
    yield server.get_uri().replace("postgresql://", "postgresql+psycopg://")


@pytest.fixture(scope="session")
def migrated_db(database_url: str, tmp_path_factory: pytest.TempPathFactory) -> str:
    """Apply the real Alembic migrations once per test session."""
    storage = tmp_path_factory.mktemp("storage")
    _use_settings(DATABASE_URL=database_url, STORAGE_DIR=str(storage))
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=BACKEND_DIR,
        env={**os.environ, "DATABASE_URL": database_url},
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    return database_url


@pytest.fixture
def db_url(migrated_db: str, tmp_path: Path) -> Iterator[str]:
    """Clean database + fresh storage directory for every test."""
    _use_settings(DATABASE_URL=migrated_db, STORAGE_DIR=str(tmp_path / "storage"))
    with get_engine().begin() as conn:
        conn.execute(
            text(
                "TRUNCATE users, documents, pages, logical_documents, extractions, extracted_fields, line_items, "
                "corrections, validation_results, processing_events, comparisons, comparison_items, "
                "page_embeddings, audit_log RESTART IDENTITY CASCADE"
            )
        )
    yield migrated_db


@pytest.fixture
def settings_override(db_url: str) -> Iterator[Callable[..., None]]:
    """Change settings for one test (env vars are restored by monkeypatch-like cleanup)."""
    saved: dict[str, str | None] = {}

    def apply(**env: str) -> None:
        for k, v in env.items():
            saved.setdefault(k, os.environ.get(k))
            os.environ[k] = v
        get_settings.cache_clear()
        reset_runtime()

    yield apply
    for k, v in saved.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v
    get_settings.cache_clear()
    reset_runtime()


@pytest.fixture
def client(db_url: str) -> Iterator[TestClient]:
    from app.main import create_app
    from app.tasks.celery_app import celery_app

    celery_app.conf.task_always_eager = True
    with TestClient(create_app(), raise_server_exceptions=False) as c:
        yield c


PASSWORD = "correct-horse-battery"



@pytest.fixture
def make_user(
    db_url: str,
    client: TestClient,
) -> Callable[[str], dict[str, str]]:
    def _make(role: str) -> dict[str, str]:
        email = f"{role}@example.com"

        with session_scope() as s:
            existing = s.execute(
                text("SELECT id FROM users WHERE email = :e"),
                {"e": email},
            ).scalar_one_or_none()

            if existing is None:
                users.create_user(s, email, PASSWORD, role)
            else:
                s.execute(
                    text("""
                        UPDATE users
                        SET password_hash = :password_hash,
                            role = :role,
                            is_active = TRUE
                        WHERE email = :email
                    """),
                    {
                        "password_hash": hash_password(PASSWORD),
                        "role": role,
                        "email": email,
                    },
                )

        resp = client.post(
            "/api/v1/auth/login",
            json={"email": email, "password": PASSWORD},
        )
        assert resp.status_code == 200, resp.text

        return {
            "Authorization": f"Bearer {resp.json()['access_token']}"
        }

    return _make


@pytest.fixture
def auth(make_user: Callable[[str], dict[str, str]]) -> dict[str, str]:
    return make_user("reviewer")


@pytest.fixture
def admin_auth(make_user: Callable[[str], dict[str, str]]) -> dict[str, str]:
    return make_user("admin")


@pytest.fixture
def rng() -> random.Random:
    return random.Random(42)


class Uploader:
    def __init__(self, client: TestClient, headers: dict[str, str]) -> None:
        self.client, self.headers = client, headers

    def __call__(self, *files: tuple[str, bytes], expect: int = 202) -> list[dict[str, Any]]:
        resp = self.client.post(
            "/api/v1/documents",
            headers=self.headers,
            files=[("files", (n, b, "application/octet-stream")) for n, b in files],
        )
        assert resp.status_code == expect, resp.text
        return resp.json()["results"]  # type: ignore[no-any-return]

    def one(self, name: str, data: bytes) -> str:
        res = self((name, data))[0]
        assert res["status"] in ("accepted", "duplicate"), res
        return str(res["document_id"])

    def status(self, doc_id: str) -> dict[str, Any]:
        r = self.client.get(f"/api/v1/documents/{doc_id}/status", headers=self.headers)
        assert r.status_code == 200, r.text
        return r.json()  # type: ignore[no-any-return]

    def doc(self, doc_id: str) -> dict[str, Any]:
        return self.client.get(f"/api/v1/documents/{doc_id}", headers=self.headers).json()  # type: ignore[no-any-return]

    def extractions(self, doc_id: str) -> list[dict[str, Any]]:
        r = self.client.get(f"/api/v1/documents/{doc_id}/extractions", headers=self.headers)
        assert r.status_code == 200, r.text
        return r.json()  # type: ignore[no-any-return]


@pytest.fixture
def upload(client: TestClient, auth: dict[str, str]) -> Uploader:
    return Uploader(client, auth)


def field_values(logical: dict[str, Any]) -> dict[str, str | None]:
    return {f["name"]: f["value"] for f in logical["fields"]}


@pytest.fixture(autouse=True)
def _cleanup_tmp() -> Iterator[None]:
    yield
    shutil.rmtree("/tmp/runtime-0", ignore_errors=True)
