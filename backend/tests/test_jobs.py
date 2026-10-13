from __future__ import annotations

import asyncio
import json

from httpx import AsyncClient

from app.core import jobs


async def test_job_runs_reports_progress_and_stores_its_result(client: AsyncClient) -> None:
    job = await jobs.create_job("test", {"n": 3})

    async def work(ctx: jobs.JobContext) -> dict:
        for i in range(3):
            await ctx.progress((i + 1) / 3, f"step {i + 1}")
        return {"total": 3}

    jobs.launch(job.id, work)
    finished = await jobs.wait(job.id, timeout=20)
    assert finished.status == "done"
    assert finished.progress == 1.0
    assert finished.result == {"total": 3}

    resp = await client.get(f"/api/v1/jobs/{job.id}")
    assert resp.status_code == 200 and resp.json()["status"] == "done"

    stream = await client.get(f"/api/v1/jobs/{job.id}/stream")
    frames = [f for f in stream.text.strip().split("\n\n") if f.strip()]
    names = [f.split("\n")[1].removeprefix("event: ") for f in frames]
    assert names[0] == "status" and names[-1] == "done"
    assert names.count("progress") == 3
    seqs = [json.loads(f.split("\n")[2].removeprefix("data: "))["seq"] for f in frames]
    assert seqs == sorted(seqs) and len(set(seqs)) == len(seqs)

    # Reattaching from a known position replays only what came after it.
    resumed = await client.get(f"/api/v1/jobs/{job.id}/stream", params={"after_seq": seqs[-2]})
    assert [f for f in resumed.text.strip().split("\n\n") if f.strip()][0].startswith(
        f"id: {seqs[-1]}"
    )


async def test_a_failing_job_surfaces_the_real_error(client: AsyncClient) -> None:
    job = await jobs.create_job("test", {})

    async def work(_ctx: jobs.JobContext) -> dict:
        raise RuntimeError("the index could not be opened")

    jobs.launch(job.id, work)
    finished = await jobs.wait(job.id, timeout=20)
    assert finished.status == "failed"
    assert "the index could not be opened" in (finished.error or "")


async def test_cancelling_stops_the_job_at_the_next_checkpoint(client: AsyncClient) -> None:
    job = await jobs.create_job("test", {})
    reached: list[int] = []

    async def work(ctx: jobs.JobContext) -> dict:
        for i in range(200):
            await ctx.progress(i / 200, f"step {i}")
            reached.append(i)
            await asyncio.sleep(0.05)
        return {}

    jobs.launch(job.id, work)
    while not reached:
        await asyncio.sleep(0.02)
    resp = await client.post(f"/api/v1/jobs/{job.id}/cancel")
    assert resp.json()["status"] == "cancelling"
    finished = await jobs.wait(job.id, timeout=20)
    assert finished.status == "cancelled"
    assert len(reached) < 200
    # Cancelling something already finished changes nothing.
    assert (await client.post(f"/api/v1/jobs/{job.id}/cancel")).json()["status"] == "cancelled"


async def test_heavy_jobs_queue_instead_of_running_side_by_side() -> None:
    running = 0
    peak = 0

    async def work(_ctx: jobs.JobContext) -> dict:
        nonlocal running, peak
        running += 1
        peak = max(peak, running)
        await asyncio.sleep(0.2)
        running -= 1
        return {}

    created = [await jobs.create_job("test", {}) for _ in range(3)]
    for job in created:
        jobs.launch(job.id, work)
    for job in created:
        assert (await jobs.wait(job.id, timeout=20)).status == "done"
    assert peak == 1


async def test_unknown_job_is_404(client: AsyncClient) -> None:
    assert (await client.get("/api/v1/jobs/nope")).status_code == 404
    assert (await client.post("/api/v1/jobs/nope/cancel")).status_code == 404
    assert (await client.get("/api/v1/jobs/nope/stream")).status_code == 404


async def test_jobs_orphaned_by_a_restart_are_marked_failed() -> None:
    job = await jobs.create_job("test", {})  # never launched: as if the process died
    assert await jobs.reconcile_orphaned_jobs() >= 1
    settled = await jobs.get_job(job.id)
    assert settled is not None and settled.status == "failed"
    assert "restart" in (settled.error or "")
