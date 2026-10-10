from __future__ import annotations

from conftest import wait_for_document
from httpx import AsyncClient


async def _upload_policy_doc(client: AsyncClient) -> str:
    files = {
        "file": (
            "policy.md",
            b"# Vacation Policy\n\nEmployees accrue two paid vacation days per month of "
            b"service, up to a maximum of twenty-four days per year. Managers must approve "
            b"requests at least two weeks in advance.",
            "text/markdown",
        )
    }
    resp = await client.post("/api/v1/documents/upload", files=files)
    document_id = resp.json()["document_id"]
    await wait_for_document(client, document_id)
    return document_id


async def test_generate_dataset_endpoint_returns_real_items(client: AsyncClient) -> None:
    document_id = await _upload_policy_doc(client)
    resp = await client.post(
        f"/api/v1/documents/{document_id}/eval/datasets/generate", json={"target_size": 10}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["document_id"] == document_id
    assert body["version"] == 1
    assert body["item_count"] > 0
    assert sum(body["categories"].values()) == body["item_count"]


async def test_generate_dataset_endpoint_versions_increment(client: AsyncClient) -> None:
    document_id = await _upload_policy_doc(client)
    first = await client.post(
        f"/api/v1/documents/{document_id}/eval/datasets/generate", json={"target_size": 10}
    )
    second = await client.post(
        f"/api/v1/documents/{document_id}/eval/datasets/generate", json={"target_size": 10}
    )
    assert first.json()["version"] == 1
    assert second.json()["version"] == 2


async def test_generate_dataset_endpoint_422_for_document_with_no_chunks(
    client: AsyncClient,
) -> None:
    resp = await client.post(
        "/api/v1/documents/does-not-exist/eval/datasets/generate", json={"target_size": 10}
    )
    assert resp.status_code == 422
    assert resp.json()["code"] == "dataset_empty"


async def test_run_benchmark_endpoint_scores_real_configs(client: AsyncClient) -> None:
    document_id = await _upload_policy_doc(client)
    resp = await client.post(
        "/api/v1/eval/benchmarks/run",
        json={
            "document_id": document_id,
            "configs": ["bm25", "hybrid"],
            "dataset_target_size": 5,
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["document_id"] == document_id
    assert len(body["config_results"]) == 2
    names = {r["name"] for r in body["config_results"]}
    assert names == {"bm25", "hybrid"}
    for result in body["config_results"]:
        assert 0.0 <= result["faithfulness"] <= 1.0
        assert result["p95_latency_ms"] >= result["p50_latency_ms"]
    assert 0.0 <= body["injection_block_rate"] <= 1.0
    assert body["pii_leak_count"] == 0
    assert body["recommended_config"] in names

    get_resp = await client.get(f"/api/v1/eval/benchmarks/{body['id']}")
    assert get_resp.status_code == 200
    assert get_resp.json()["id"] == body["id"]


async def test_run_benchmark_endpoint_422_for_document_with_no_chunks(
    client: AsyncClient,
) -> None:
    resp = await client.post(
        "/api/v1/eval/benchmarks/run",
        json={"document_id": "does-not-exist", "configs": ["bm25"], "dataset_target_size": 5},
    )
    assert resp.status_code == 422
    assert resp.json()["code"] == "dataset_empty"


async def test_get_benchmark_endpoint_404_for_unknown_id(client: AsyncClient) -> None:
    resp = await client.get("/api/v1/eval/benchmarks/does-not-exist")
    assert resp.status_code == 404
    assert resp.json()["code"] == "benchmark_not_found"
