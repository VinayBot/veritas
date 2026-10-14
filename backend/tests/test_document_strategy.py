"""After upload the app measures strategies on the document and answers it with the best."""

from __future__ import annotations

import asyncio
import json
import uuid

import pytest
from conftest import upload_and_wait_ready, wait_for_enrichment
from httpx import AsyncClient

from app.core.config import get_settings
from app.rag_engines import document_strategy
from app.rag_engines.registry import default_strategy_id

POLICY = (
    "# Travel Policy\n\nBusiness travel under one thousand dollars needs only the direct "
    "manager's approval. Trips between one thousand and five thousand dollars need the Vice "
    "President of Operations. Anything over five thousand dollars also needs the Chief "
    "Financial Officer, Dana Whitfield, and must be requested fourteen days ahead.\n\n"
    "# Remote Work\n\nAfter a ninety-day probation, employees may work remotely up to three "
    "days a week with approval from Priya Raman, the People Operations Lead. The home office "
    "stipend is six hundred dollars a year, paid by Northwind Finance each January.\n\n"
    "# Equipment\n\nLaptops are issued by the IT Service Desk in Leeds and must be returned "
    "within five business days of leaving the company. Lost devices are reported to IT "
    "Security within one hour so that a remote wipe can start."
)


async def _upload(client: AsyncClient) -> str:
    text = f"{POLICY}\n\nRevision {uuid.uuid4()}.".encode()
    doc = await upload_and_wait_ready(client, "travel.md", text, "text/markdown")
    await wait_for_enrichment(client, doc["id"])
    return doc["id"]


async def test_a_new_document_is_measured_and_answered_with_its_best_strategy(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(get_settings(), "auto_measure_on_ingest", True)
    document_id = await _upload(client)

    doc: dict = {}
    for _ in range(300):  # real model calls: a few minutes at most
        doc = (await client.get(f"/api/v1/documents/{document_id}")).json()
        if doc["measure_status"] in ("done", "skipped", "failed"):
            break
        await asyncio.sleep(1)
    assert doc["measure_status"] == "done", doc.get("measure_error")

    rec = (await client.get(f"/api/v1/documents/{document_id}/recommendation")).json()
    measured = rec["measured"]
    assert measured is not None and len(measured["ranking"]) >= 2
    top = measured["ranking"][0]
    # The document is now answered with the highest scorer, and the card can say so.
    assert doc["preferred_strategy"] == top["strategy"]
    assert doc["strategy_source"] == "measured"
    assert rec["current_default"] == top["strategy"]
    assert 0.0 <= top["score"] <= 1.0
    strategies = (await client.get(f"/api/v1/rag/strategies?document_id={document_id}")).json()
    assert strategies["default"] == top["strategy"]

    # A question that names no strategy is answered with it.
    resp = await client.post(
        "/api/v1/chat",
        json={"message": "How much is the home office stipend?", "document_id": document_id},
    )
    session = next(
        json.loads(line.removeprefix("data: "))
        for block in resp.text.split("\n\n")
        if block.startswith("event: session")
        for line in block.splitlines()
        if line.startswith("data: ")
    )
    assert session["strategy"] == top["strategy"]


async def test_a_users_choice_for_a_document_wins_until_handed_back(client: AsyncClient) -> None:
    document_id = await _upload(client)
    assert (await document_strategy.effective_strategy(document_id)) == (
        default_strategy_id(),
        "default",
    )
    other = "hybrid" if default_strategy_id() != "hybrid" else "hybrid_rerank"
    resp = await client.put(f"/api/v1/documents/{document_id}/strategy", json={"strategy": other})
    assert resp.json() == {"document_id": document_id, "strategy": other, "source": "chosen"}
    assert (await document_strategy.effective_strategy(document_id)) == (other, "chosen")
    # The workspace default is untouched; only this document changed.
    assert default_strategy_id() != other or other == "hybrid_rerank"

    bad = await client.put(f"/api/v1/documents/{document_id}/strategy", json={"strategy": "nope"})
    assert bad.status_code == 422
    back = await client.put(f"/api/v1/documents/{document_id}/strategy", json={"strategy": None})
    assert back.json()["source"] == "default"


async def test_waiting_measurements_run_newest_first() -> None:
    """Several uploads queue their measurements; the most recent one is the document the user
    is looking at, so it goes next."""
    order: list[str] = []
    release = asyncio.Event()

    async def first() -> None:
        async with document_strategy._measure_slot():
            order.append("first")
            await release.wait()

    async def later(name: str) -> None:
        async with document_strategy._measure_slot():
            order.append(name)

    running = asyncio.ensure_future(first())
    await asyncio.sleep(0.01)
    older = asyncio.ensure_future(later("older"))
    await asyncio.sleep(0.01)
    newer = asyncio.ensure_future(later("newer"))
    await asyncio.sleep(0.01)
    release.set()
    await asyncio.gather(running, older, newer)
    assert order == ["first", "newer", "older"]


async def test_a_requested_measurement_keeps_the_jobs_priority(monkeypatch) -> None:
    """Run from the Re-measure button (a job), the measurement must not demote itself to
    housekeeping: housekeeping waits while any job runs, including its own."""
    from app.llm import client as llm_client

    levels: list[int] = []

    async def fake_update(document_id, **fields):  # noqa: ANN001, ANN003, ARG001
        levels.append(llm_client._level.get())
        raise RuntimeError("stop here")

    monkeypatch.setattr(document_strategy, "_update", fake_update)
    llm_client.mark_background(llm_client.FOREGROUND)
    with pytest.raises(RuntimeError):
        await document_strategy.auto_measure("doc", requested=True)
    with pytest.raises(RuntimeError):
        await document_strategy.auto_measure("doc")
    assert levels == [llm_client.FOREGROUND, llm_client.HOUSEKEEPING]


async def test_measurements_cut_off_by_a_restart_are_marked_for_rerunning(
    client: AsyncClient,
) -> None:
    document_id = await _upload(client)
    await document_strategy._update(document_id, measure_status="running")
    assert await document_strategy.reconcile_interrupted_measurements() >= 1
    doc = (await client.get(f"/api/v1/documents/{document_id}")).json()
    assert doc["measure_status"] == "failed"
    assert "restart" in doc["measure_error"]


async def test_a_requested_measurement_does_not_wait_behind_automatic_ones(monkeypatch) -> None:
    """Uploads keep queueing automatic measurements, newest first. Re-measure must not join
    that queue, or it could wait indefinitely while holding the job slot."""
    statuses: list[str] = []

    async def fake_update(document_id, **fields):  # noqa: ANN001, ANN003, ARG001
        statuses.append(fields.get("measure_status", ""))
        if fields.get("measure_status") == "running":
            raise RuntimeError("reached the measurement")

    monkeypatch.setattr(document_strategy, "_update", fake_update)
    release = asyncio.Event()

    async def automatic_in_progress() -> None:
        async with document_strategy._measure_slot():
            await release.wait()

    holder = asyncio.ensure_future(automatic_in_progress())
    await asyncio.sleep(0.01)
    with pytest.raises(RuntimeError):
        await asyncio.wait_for(document_strategy.auto_measure("doc", requested=True), 2)
    assert statuses == ["queued", "running"]
    release.set()
    await holder
