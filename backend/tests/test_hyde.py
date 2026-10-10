from __future__ import annotations

from app.retrieval.hyde import hyde_rewrite


async def test_hyde_falls_back_to_raw_query_when_llm_unavailable() -> None:
    query = "What is the vacation policy?"
    # A model name no provider recognizes — guarantees a real (not mocked) failure path.
    result = await hyde_rewrite(query, model="ollama/this-model-does-not-exist:0b")
    assert result == query
