"""Golden retrieval: real documents with known answers (tests/fixtures/golden_qa.json),
ingested through the real pipeline, and every question asked of hybrid search with reranking.
A chunk containing the question's evidence (a verbatim quote of the sentence that answers it)
must come back in the top 5. No language model is
involved, so this runs everywhere, CI included. Includes a French document and facts placed
in the last chapters of a 61-page handbook."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from conftest import upload_and_wait_ready
from httpx import AsyncClient

FIXTURES = Path(__file__).resolve().parents[2] / "tests" / "fixtures"
GOLDEN = json.loads((FIXTURES / "golden_qa.json").read_text(encoding="utf-8"))
MIME = {".pdf": "application/pdf", ".docx": "application/octet-stream"}


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text.replace("\u2019", "'").replace("\u2018", "'")).lower()


def _cases():
    for doc in GOLDEN.values():
        for qa in doc["qa"]:
            yield pytest.param(doc["file"], qa, id=f"{doc['file']}: {qa['question'][:50]}")


_ingested: dict[str, str] = {}


async def _document_id(client: AsyncClient, filename: str) -> str:
    if filename not in _ingested:
        path = FIXTURES / filename
        doc = await upload_and_wait_ready(
            client, filename, path.read_bytes(), MIME[path.suffix], timeout=600
        )
        _ingested[filename] = doc["id"]
    return _ingested[filename]


@pytest.mark.parametrize(("filename", "qa"), list(_cases()))
async def test_the_answer_is_retrieved_in_the_top_five(client, filename: str, qa: dict) -> None:
    if not await _still_there(client):
        _ingested.clear()
    document_id = await _document_id(client, filename)
    resp = await client.post(
        "/api/v1/retrieval/search",
        json={"query": qa["question"], "document_id": document_id, "k": 5, "rerank": True},
    )
    assert resp.status_code == 200, resp.text
    evidence = _norm(qa["evidence"])
    ranks = [i + 1 for i, hit in enumerate(resp.json()["hits"]) if evidence in _norm(hit["text"])]
    assert ranks, f"no top-5 chunk contains {qa['evidence']!r} for {qa['question']!r}"


async def _still_there(client: AsyncClient) -> bool:
    """Each test module gets a fresh database in some runs; re-ingest if ours is gone."""
    for document_id in _ingested.values():
        resp = await client.get(f"/api/v1/documents/{document_id}")
        if resp.status_code != 200:
            return False
    return True
