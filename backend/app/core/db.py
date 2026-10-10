"""Async SQLAlchemy engine/session. SQLite file lives under settings.data_dir."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy import event
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from app.core.config import get_settings


class Base(DeclarativeBase):
    pass


def _make_engine() -> AsyncEngine:
    settings = get_settings()
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    is_sqlite = settings.database_url.startswith("sqlite")

    # Ingestion now runs as detached background tasks (see app/ingestion/service.py) that can
    # genuinely overlap — several documents mid-pipeline at once, each opening its own
    # session — where before there was always exactly one synchronous request touching the DB
    # at a time. Reproduced by the full test suite, not assumed: the default pool intermittently
    # handed out a connection that another coroutine had concurrently torn down ("database is
    # locked" / "attempt to write a readonly database" / aiosqlite's "no active connection").
    # pool_pre_ping discards and transparently replaces a connection that fails a liveness
    # check instead of handing it out as-is; busy_timeout makes a genuinely contended
    # statement retry for up to 30s instead of failing immediately. (StaticPool — one shared
    # connection — looked tempting here too, but its internal lock binds to whichever asyncio
    # event loop first touches it, which breaks the moment a *different* loop uses it; fine
    # for a server's one long-lived loop, but it broke immediately under pytest-asyncio's
    # fresh loop per test function, so it's deliberately not used.)
    engine = create_async_engine(
        settings.database_url,
        echo=False,
        pool_pre_ping=is_sqlite,
    )

    if is_sqlite:

        @event.listens_for(engine.sync_engine, "connect")
        def _set_sqlite_pragmas(dbapi_connection: object, _connection_record: object) -> None:
            cursor = dbapi_connection.cursor()  # type: ignore[attr-defined]
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA busy_timeout=30000")
            cursor.close()

    return engine


_engine = _make_engine()
_session_factory = async_sessionmaker(_engine, expire_on_commit=False)


async def init_db() -> None:
    async with _engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


@asynccontextmanager
async def session_scope() -> AsyncIterator[AsyncSession]:
    async with _session_factory() as session:
        yield session


async def get_session() -> AsyncIterator[AsyncSession]:
    async with _session_factory() as session:
        yield session
