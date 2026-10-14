"""Settings a user can change while the app is running, persisted in the database and laid
over the `.env` defaults.

`.env` stays the zero-config path: with nothing stored here, every value comes from
app/core/config.py exactly as before. A stored value wins until it is cleared.

Reads are synchronous (model lookups happen on hot, sync code paths), so values are held in
a process-wide cache that is loaded at startup and updated on every write.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import JSON, DateTime, String, select
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, session_scope

KNOWN_KEYS = (
    "generator_model",
    "judge_model",
    "council_models",
    "chairman_model",
    "embedding_model",
    "reranker_model",
    "default_strategy",
)


class RuntimeSetting(Base):
    __tablename__ = "runtime_settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[Any] = mapped_column(JSON)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


_cache: dict[str, Any] = {}


def current() -> dict[str, Any]:
    return _cache


async def load() -> dict[str, Any]:
    async with session_scope() as session:
        rows = (await session.execute(select(RuntimeSetting))).scalars().all()
    _cache.clear()
    _cache.update({row.key: row.value for row in rows if row.key in KNOWN_KEYS})
    return dict(_cache)


async def set_value(key: str, value: Any) -> None:
    if key not in KNOWN_KEYS:
        raise KeyError(f"Unknown runtime setting: {key!r}")
    async with session_scope() as session:
        row = await session.get(RuntimeSetting, key)
        if value is None:
            if row is not None:
                await session.delete(row)
        elif row is None:
            session.add(RuntimeSetting(key=key, value=value, updated_at=datetime.now(UTC)))
        else:
            row.value = value
            row.updated_at = datetime.now(UTC)
        await session.commit()
    if value is None:
        _cache.pop(key, None)
    else:
        _cache[key] = value
