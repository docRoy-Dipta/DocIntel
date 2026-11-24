"""Fixed-window rate limiting. Redis-backed when available, in-memory otherwise."""

from __future__ import annotations

import logging
import time
from collections import defaultdict
from typing import Protocol


class RateLimiter(Protocol):
    def hit(self, key: str, limit: int, window_seconds: int = 60) -> bool:
        """Record a hit. Returns True if allowed, False if the limit is exceeded."""
        ...


class MemoryRateLimiter:
    def __init__(self) -> None:
        self._counts: dict[tuple[str, int], int] = defaultdict(int)

    def hit(self, key: str, limit: int, window_seconds: int = 60) -> bool:
        window = int(time.time() // window_seconds)
        self._counts = defaultdict(int, {k: v for k, v in self._counts.items() if k[1] >= window - 1})
        self._counts[(key, window)] += 1
        return self._counts[(key, window)] <= limit


class RedisRateLimiter:
    def __init__(self, client: object) -> None:
        self._client = client

    def hit(self, key: str, limit: int, window_seconds: int = 60) -> bool:
        window = int(time.time() // window_seconds)
        redis_key = f"rl:{key}:{window}"
        pipe = self._client.pipeline()  # type: ignore[attr-defined]
        pipe.incr(redis_key)
        pipe.expire(redis_key, window_seconds * 2)
        count = pipe.execute()[0]
        return int(count) <= limit


def build_limiter(redis_url: str | None) -> RateLimiter:
    """Redis-backed limiter shared by all processes if Redis answers, otherwise per-process memory."""
    if redis_url:
        try:
            import redis

            client = redis.Redis.from_url(redis_url, socket_connect_timeout=1, socket_timeout=1)
            client.ping()
            return RedisRateLimiter(client)
        except Exception as exc:  # noqa: BLE001 - any connection problem means "fall back"
            logging.getLogger(__name__).warning("Redis unavailable for rate limiting, using memory: %s", exc)
    return MemoryRateLimiter()
