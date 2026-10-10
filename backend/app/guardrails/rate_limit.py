"""Per-session rate limiting: a fixed one-minute window counter, in memory. Same scale caveat
as the semantic cache (app/retrieval/semantic_cache.py) — fine for one process, not for a
multi-process deployment, which would need Redis. Not built for the same reason: nothing here
runs more than one backend process.
"""

from __future__ import annotations

import time

from app.core.config import get_settings

_WINDOW_SECONDS = 60
_hits: dict[str, list[float]] = {}


def check(session_id: str) -> bool:
    """Returns True if the request is allowed, False if the session is over its limit."""
    limit = get_settings().rate_limit_per_minute
    now = time.time()
    window_start = now - _WINDOW_SECONDS

    timestamps = [t for t in _hits.get(session_id, []) if t >= window_start]
    if len(timestamps) >= limit:
        _hits[session_id] = timestamps
        return False

    timestamps.append(now)
    _hits[session_id] = timestamps
    return True


def clear() -> None:
    _hits.clear()
