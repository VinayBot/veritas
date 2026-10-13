from __future__ import annotations

import json

import pytest
from conftest import upload_and_wait_ready
from httpx import AsyncClient

from app.core import jobs, runtime_settings
from app.llm import models_catalog
from app.llm.models_config import get_model_config

DOC = b"# Handbook\n\nThe quartz archive is audited every lunar quarter by the records team.\n"


@pytest.fixture(autouse=True)
async def _restore_selection():
    yield
    for key in runtime_settings.KNOWN_KEYS:
        await runtime_settings.set_value(key, None)


async def test_local_models_lists_what_is_really_installed_with_roles(client: AsyncClient) -> None:
    body = (await client.get("/api/v1/models/local")).json()
    assert body["ollama"]["status"] == "up"
    chat = {m["id"]: m for m in body["chat_models"]}
    generator = get_model_config().generator
    assert generator in chat
    model = chat[generator]
    assert model["disk_bytes"] > 0
    assert model["parameter_size"] and model["quantization"] and model["family"]
    assert model["context_length"] > 0
    assert isinstance(model["loaded"], bool)
    assert model["roles"]["generator"]
    assert body["selection"]["generator"] == generator
    # The safety classifier is installed, but never offered as a chat model.
    guard = next(m for m in body["chat_models"] if "guard" in m["id"])
    assert not guard["roles"]["generator"] and not guard["roles"]["council_member"]
    # No cloud key is set in tests, so no cloud model is listed.
    assert not any(m["cloud"] for m in body["chat_models"])
    assert body["embedding_models"] and body["reranker_models"]
    assert body["budget"]["tier"] in {"8gb", "16gb"}
    assert body["budget"]["selected_bytes"] > 0


async def test_ollama_down_is_reported_exactly_with_the_command_to_start_it(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.core.config import get_settings

    monkeypatch.setattr(get_settings(), "ollama_base_url", "http://127.0.0.1:9")
    body = (await client.get("/api/v1/models/local")).json()
    assert body["ollama"]["status"] == "down"
    assert "ConnectError" in body["ollama"]["error"]
    assert "ollama serve" in body["ollama"]["fix"]
    assert body["chat_models"] == []


async def test_switching_the_generator_applies_to_the_next_answer(client: AsyncClient) -> None:
    doc = await upload_and_wait_ready(client, "handbook.md", DOC, "text/markdown")
    catalog = (await client.get("/api/v1/models/local")).json()
    current = catalog["selection"]["generator"]
    other = next(
        m["id"] for m in catalog["chat_models"] if m["roles"]["generator"] and m["id"] != current
    )
    resp = await client.put("/api/v1/models/selection", json={"generator": other})
    assert resp.status_code == 200 and resp.json()["selection"]["generator"] == other
    assert get_model_config().generator == other

    chat = await client.post(
        "/api/v1/chat",
        json={"message": "How often is the quartz archive audited?", "document_id": doc["id"]},
    )
    done = json.loads(
        next(b for b in chat.text.split("\n\n") if b.startswith("event: done")).split("data: ")[1]
    )
    report = (await client.get(f"/api/v1/reports/{done['report_id']}")).json()
    assert report["routing"]["model_used"] == other
    assert other in report["usage"]["by_model"]

    reset = await client.post("/api/v1/models/reset")
    assert reset.json()["selection"]["generator"] == current


async def test_invalid_pairings_are_blocked_with_the_reason(client: AsyncClient) -> None:
    guard = get_model_config().guard
    as_generator = await client.put("/api/v1/models/selection", json={"generator": guard})
    assert as_generator.status_code == 422
    assert as_generator.json()["code"] == "invalid_model_selection"
    assert "Safety classifier" in as_generator.json()["message"]

    missing = await client.put(
        "/api/v1/models/selection", json={"generator": "ollama/not-installed:1b"}
    )
    assert (
        missing.status_code == 422 and "ollama pull not-installed:1b" in missing.json()["message"]
    )

    embedder = await client.put(
        "/api/v1/models/selection", json={"embedding": "ollama/llama3.2:3b"}
    )
    assert (
        embedder.status_code == 422
        and "not a supported embedding model" in embedder.json()["message"]
    )

    duplicate = await client.put(
        "/api/v1/models/selection",
        json={"council": [get_model_config().generator, get_model_config().generator]},
    )
    assert duplicate.status_code == 422
    assert get_model_config().guard == guard  # nothing was changed by a refused request


def test_budget_warns_when_the_selection_does_not_fit(monkeypatch: pytest.MonkeyPatch) -> None:
    config = get_model_config()
    huge = [
        {"id": m, "vram_bytes": None, "disk_bytes": 9 * 1024**3} for m in config.all_llm_models()
    ]
    assessed = models_catalog.assess_budget(config, huge)
    assert assessed["over_budget"] and "over the" in assessed["warning"]
    small = [{"id": m, "vram_bytes": 10, "disk_bytes": 10} for m in config.all_llm_models()]
    assert models_catalog.assess_budget(config, small)["warning"] is None


async def test_changing_the_embedding_model_blocks_search_until_the_document_is_reindexed(
    client: AsyncClient,
) -> None:
    doc = await upload_and_wait_ready(client, "handbook.md", DOC, "text/markdown")
    question = {"message": "How often is the quartz archive audited?", "document_id": doc["id"]}
    original = get_model_config().embedding
    other = "BAAI/bge-small-en-v1.5"

    switched = await client.put("/api/v1/models/selection", json={"embedding": other})
    assert switched.status_code == 200
    index = switched.json()["index"]
    assert index["active_embedding_model"] == other
    assert index["stale_count"] >= 1
    assert any(
        d["id"] == doc["id"] and d["embedding_model"] == original for d in index["stale_documents"]
    )

    # Never served from mismatched embeddings: the question is refused, with the reason.
    refused = await client.post("/api/v1/chat", json=question)
    error = json.loads(
        next(b for b in refused.text.split("\n\n") if b.startswith("event: error")).split("data: ")[
            1
        ]
    )
    assert error["code"] == "index_mismatch"
    assert original in error["message"] and other in error["message"]
    assert "event: token" not in refused.text

    started = await client.post("/api/v1/models/reindex", json={"document_ids": [doc["id"]]})
    job = await jobs.wait(started.json()["job_id"], timeout=600)
    assert job.status == "done", job.error
    assert job.result["documents"] == 1 and job.result["chunks"] == doc["chunk_count"]

    status = (await client.get("/api/v1/models/index-status")).json()
    assert not any(d["id"] == doc["id"] for d in status["stale_documents"])
    answered = await client.post("/api/v1/chat", json=question)
    assert "event: token" in answered.text and "event: error" not in answered.text


async def test_a_saved_choice_of_a_model_that_was_removed_falls_back_to_the_default(
    client: AsyncClient,
) -> None:
    """`ollama rm` after choosing a model used to leave every answer failing with "model not
    found". The saved choice is dropped and the configured default takes over."""
    from app.core import runtime_settings
    from app.core.config import get_settings

    await runtime_settings.set_value("generator_model", "ollama/this-model-was-removed:7b")
    await runtime_settings.set_value(
        "council_models", ["ollama/this-model-was-removed:7b", get_settings().default_llm_model]
    )
    try:
        state = (await client.get("/api/v1/models/local")).json()
        assert state["selection"]["generator"] == get_settings().default_llm_model
        assert state["selection"]["council"] == [get_settings().default_llm_model]
    finally:
        await runtime_settings.set_value("generator_model", None)
        await runtime_settings.set_value("council_models", None)
