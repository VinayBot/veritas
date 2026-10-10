from __future__ import annotations

from httpx import AsyncClient


async def test_redteam_run_endpoint_returns_real_aggregates(client: AsyncClient) -> None:
    resp = await client.post("/api/v1/redteam/run")
    assert resp.status_code == 200
    body = resp.json()
    assert body["total_attacks"] >= 40
    assert 0.0 <= body["block_rate"] <= 1.0
    assert 0.0 <= body["false_positive_rate"] <= 1.0
    assert body["by_category"]
