"""Rate limiting, at two levels, with one fixed one-minute window counter:

- **Per session** (`check`), inside the input guardrail: a conversation that sends too many
  questions is stopped and the decision is audited like any other guardrail.
- **Per client** (`limit_client`), a FastAPI dependency on the endpoints that start model
  work (chat, upload, comparisons, benchmarks, the red-team run). The session id is chosen by
  the client, and a request without one gets a fresh id, so a per-session limit alone is
  bypassed by changing or omitting it; the client's address cannot be chosen that way.

Counters live in Redis when REDIS_URL is set, so every backend process shares them, and in
process memory otherwise (one process, which is how the app runs locally). A Redis outage
falls back to memory rather than refusing every request.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Awaitable, Callable
from typing import Any, Protocol

from fastapi import Request

from app.core.config import get_settings
from app.core.errors import AppError

logger = logging.getLogger(__name__)

_WINDOW_SECONDS = 60


class _Counter(Protocol):
    def hit(self, key: str, limit: int) -> bool: ...

    def clear(self) -> None: ...


class MemoryCounter:
    def __init__(self) -> None:
        self._hits: dict[str, list[float]] = {}

    def hit(self, key: str, limit: int) -> bool:
        now = time.time()
        recent = [t for t in self._hits.get(key, []) if t >= now - _WINDOW_SECONDS]
        allowed = len(recent) < limit
        if allowed:
            recent.append(now)
        self._hits[key] = recent
        return allowed

    def clear(self) -> None:
        self._hits.clear()


class RedisCounter:
    """INCR on a key per window; the key expires with its window."""

    def __init__(self, url: str) -> None:
        import redis

        self._redis: Any = redis.Redis.from_url(url, socket_timeout=1.0)
        self._fallback = MemoryCounter()

    def hit(self, key: str, limit: int) -> bool:
        window = int(time.time() // _WINDOW_SECONDS)
        redis_key = f"veritas:ratelimit:{key}:{window}"
        try:
            pipe = self._redis.pipeline()
            pipe.incr(redis_key)
            pipe.expire(redis_key, _WINDOW_SECONDS * 2)
            count, _ = pipe.execute()
        except Exception as exc:  # noqa: BLE001 — an outage must not take the API down
            logger.warning("Rate limit: Redis unavailable (%s); counting in memory", exc)
            return self._fallback.hit(key, limit)
        return int(count) <= limit

    def clear(self) -> None:
        try:
            for key in self._redis.scan_iter("veritas:ratelimit:*"):
                self._redis.delete(key)
        except Exception:  # noqa: BLE001
            pass
        self._fallback.clear()


_counter: _Counter | None = None


def counter() -> _Counter:
    global _counter
    if _counter is None:
        url = get_settings().redis_url
        _counter = RedisCounter(url) if url else MemoryCounter()
    return _counter


def check(session_id: str) -> bool:
    """True if this session may ask another question this minute."""
    return counter().hit(f"session:{session_id}", get_settings().rate_limit_per_minute)


def client_key(request: Request) -> str:
    """The client's address. Behind a proxy that sets X-Forwarded-For, its first entry; the
    app does not run behind one by default, so the header is only trusted when configured."""
    if get_settings().trust_forwarded_for:
        forwarded = request.headers.get("x-forwarded-for", "")
        if forwarded.strip():
            return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def limit_client(scope: str) -> Callable[[Request], Awaitable[None]]:
    """A dependency that allows CLIENT_RATE_LIMIT_PER_MINUTE requests per client per minute
    to the endpoints sharing `scope`, and answers 429 with Retry-After beyond that."""

    async def dependency(request: Request) -> None:
        limit = get_settings().client_rate_limit_per_minute
        if limit <= 0:
            return
        if not counter().hit(f"client:{scope}:{client_key(request)}", limit):
            raise RateLimitedError(scope)

    return dependency


class RateLimitedError(AppError):
    def __init__(self, scope: str) -> None:
        super().__init__(
            "rate_limited",
            f"Too many {scope} requests from this client in the last minute. Try again shortly.",
            status_code=429,
        )
        self.headers = {"Retry-After": str(_WINDOW_SECONDS)}


def clear() -> None:
    counter().clear()
