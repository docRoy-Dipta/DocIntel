"""Process-wide singletons (storage, embedder, extractor), created lazily from settings."""

from __future__ import annotations

from functools import lru_cache

from app.ai.embeddings import Embedder, get_embedder
from app.ai.extractor import Extractor, get_extractor
from app.core.config import get_settings
from app.core.ratelimit import RateLimiter, build_limiter
from app.services.storage import LocalStorage


@lru_cache
def get_storage() -> LocalStorage:
    return LocalStorage(get_settings().storage_dir)


@lru_cache
def get_embedder_cached() -> Embedder:
    return get_embedder(get_settings())


@lru_cache
def get_limiter() -> RateLimiter:
    s = get_settings()
    return build_limiter(None if s.celery_eager else s.redis_url)


@lru_cache
def get_extractor_cached() -> Extractor:
    return get_extractor(get_settings(), get_limiter())


def reset_runtime() -> None:
    for fn in (get_storage, get_embedder_cached, get_limiter, get_extractor_cached):
        fn.cache_clear()
