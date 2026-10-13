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
            "configs": ["hybrid", "hybrid_rerank"],
            "dataset_target_size": 5,
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["document_id"] == document_id
    assert len(body["config_results"]) == 2
    names = {r["name"] for r in body["config_results"]}
    assert names == {"hybrid", "hybrid_rerank"}
    for result in body["config_results"]:
        assert result["faithfulness"] is None or 0.0 <= result["faithfulness"] <= 1.0
        assert result["p95_latency_ms"] >= result["p50_latency_ms"]
        assert result["samples"] and result["samples"][0]["answer"]
    assert 0.0 <= body["injection_block_rate"] <= 1.0
    assert body["pii_leak_count"] == 0
    assert body["recommended_config"] in names
    # Provenance: which questions, how many, which models.
    assert body["harness_version"] == 2
    assert body["dataset_id"] and body["n_items"] > 0
    assert body["run_config"]["judge"] and body["run_config"]["generator"]

    get_resp = await client.get(f"/api/v1/eval/benchmarks/{body['id']}")
    assert get_resp.status_code == 200
    assert get_resp.json()["id"] == body["id"]


async def test_run_benchmark_endpoint_422_for_document_with_no_chunks(
    client: AsyncClient,
) -> None:
    resp = await client.post(
        "/api/v1/eval/benchmarks/run",
        json={
            "document_id": "does-not-exist",
            "configs": ["hybrid"],
            "dataset_target_size": 5,
        },
    )
    assert resp.status_code == 422
    assert resp.json()["code"] == "dataset_empty"


async def test_get_benchmark_endpoint_404_for_unknown_id(client: AsyncClient) -> None:
    resp = await client.get("/api/v1/eval/benchmarks/does-not-exist")
    assert resp.status_code == 404
    assert resp.json()["code"] == "benchmark_not_found"


async def test_runs_on_the_same_eval_set_are_comparable_and_say_so(client: AsyncClient) -> None:
    """Two runs must answer the same questions for a delta between them to mean anything."""
    document_id = await _upload_policy_doc(client)
    body = {
        "document_id": document_id,
        "configs": ["hybrid"],
        "dataset_target_size": 5,
        "include_safety": False,
    }
    first = (await client.post("/api/v1/eval/benchmarks/run", json=body)).json()
    second = (await client.post("/api/v1/eval/benchmarks/run", json=body)).json()
    assert first["dataset_id"] == second["dataset_id"]
    assert first["n_items"] == second["n_items"]
    assert first["injection_block_rate"] is None  # not run, not zero

    datasets = (await client.get(f"/api/v1/documents/{document_id}/eval/datasets")).json()
    assert [d["id"] for d in datasets["datasets"]] == [first["dataset_id"]]

    history = (await client.get(f"/api/v1/documents/{document_id}/eval/benchmarks")).json()
    assert [r["id"] for r in history["runs"]] == [first["id"], second["id"]]
    # The history listing omits per-question samples; a single run has them.
    assert history["runs"][0]["config_results"][0]["samples"] == []


async def test_unknown_strategy_is_rejected_before_anything_runs(client: AsyncClient) -> None:
    document_id = await _upload_policy_doc(client)
    resp = await client.post(
        "/api/v1/eval/benchmarks/run",
        json={"document_id": document_id, "configs": ["bm25"], "dataset_target_size": 5},
    )
    assert resp.status_code == 422
    assert resp.json()["code"] == "invalid_strategy"


async def test_benchmark_runs_as_a_background_job_with_real_progress(client: AsyncClient) -> None:
    from app.core import jobs

    document_id = await _upload_policy_doc(client)
    started = await client.post(
        "/api/v1/eval/benchmarks/start",
        json={
            "document_id": document_id,
            "configs": ["hybrid"],
            "dataset_target_size": 5,
            "include_safety": False,
        },
    )
    assert started.status_code == 200
    job_id = started.json()["job_id"]
    job = await jobs.wait(job_id, timeout=600)
    assert job.status == "done", job.error
    run = await client.get(f"/api/v1/eval/benchmarks/{job.result['benchmark_run_id']}")
    assert run.status_code == 200

    stream = await client.get(f"/api/v1/jobs/{job_id}/stream")
    events = [b.split("\n")[1].removeprefix("event: ") for b in stream.text.strip().split("\n\n")]
    assert events[-1] == "done"
    assert "progress" in events
    progress = [
        __import__("json").loads(b.split("\n")[2].removeprefix("data: "))["progress"]
        for b in stream.text.strip().split("\n\n")
        if "event: progress" in b
    ]
    assert progress == sorted(progress)  # only ever moves forward
