"""Infrastructure added for the overhaul: additive schema migration, the local-inference
lock, and rebuilding the in-memory keyword index at startup."""

from __future__ import annotations

import threading
import time

from conftest import upload_and_wait_ready
from httpx import AsyncClient
from sqlalchemy import Column, Integer, MetaData, String, Table, create_engine, inspect, text

from app.core.inference_lock import run_exclusive
from app.stores.bm25 import get_bm25_index, rebuild_bm25_index


def test_migration_adds_missing_columns_and_keeps_existing_rows(tmp_path, monkeypatch) -> None:
    from app.core import migrate

    engine = create_engine(f"sqlite:///{tmp_path}/m.db")
    old = MetaData()
    Table("things", old, Column("id", Integer, primary_key=True), Column("name", String(32)))
    old.create_all(engine)
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO things (id, name) VALUES (1, 'kept')"))

    new = MetaData()
    Table(
        "things",
        new,
        Column("id", Integer, primary_key=True),
        Column("name", String(32)),
        Column("variant", String(32), nullable=False, default="default"),
        Column("note", String(64), nullable=True),
    )

    class _Base:
        metadata = new

    monkeypatch.setattr(migrate, "Base", _Base)
    with engine.begin() as conn:
        added = migrate.add_missing_columns(conn)
        assert sorted(added) == ["things.note", "things.variant"]
        assert migrate.add_missing_columns(conn) == []  # idempotent

    with engine.begin() as conn:
        columns = {c["name"] for c in inspect(conn).get_columns("things")}
        assert {"variant", "note"} <= columns
        row = conn.execute(text("SELECT name, variant, note FROM things WHERE id = 1")).one()
    assert tuple(row) == ("kept", "default", None)


def test_inference_lock_never_lets_two_calls_overlap() -> None:
    active = 0
    max_active = 0
    guard = threading.Lock()

    def work() -> None:
        nonlocal active, max_active
        with guard:
            active += 1
            max_active = max(max_active, active)
        time.sleep(0.02)
        with guard:
            active -= 1

    threads = [threading.Thread(target=run_exclusive, args=(work,)) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert max_active == 1


async def test_keyword_index_is_rebuilt_from_the_chunks_table(client: AsyncClient) -> None:
    doc = await upload_and_wait_ready(
        client,
        "bm25-restart.md",
        b"# Obsidian Lantern\n\nThe obsidian lantern protocol governs night shifts.",
        "text/markdown",
    )
    index = get_bm25_index()
    assert index.search("obsidian lantern", k=3, doc_id=doc["id"])

    # What a backend restart does to an in-memory index.
    index.rebuild([], [], [])
    assert index.search("obsidian lantern", k=3, doc_id=doc["id"]) == []

    await rebuild_bm25_index()
    assert index.size() > 0
    assert index.search("obsidian lantern", k=3, doc_id=doc["id"])
