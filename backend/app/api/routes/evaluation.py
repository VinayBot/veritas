from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.schemas.evaluation import (
    BenchmarkRunListResponse,
    BenchmarkRunResponse,
    ConfigResultOut,
    DatasetListResponse,
    DatasetOut,
    GenerateDatasetRequest,
    GenerateDatasetResponse,
    RunBenchmarkRequest,
    StartedJob,
)
from app.core import jobs
from app.core.errors import AppError
from app.evaluation import service
from app.evaluation.datasets import load_dataset
from app.evaluation.models import BenchmarkRun
from app.guardrails.rate_limit import limit_client
from app.rag_engines.registry import UnknownStrategyError, get_strategy

router = APIRouter(tags=["evaluation"])


def benchmark_run_response(run: BenchmarkRun, include_samples: bool = True) -> BenchmarkRunResponse:
    results = []
    for raw in run.config_results:
        data = dict(raw)
        if not include_samples:
            data["samples"] = []
        results.append(ConfigResultOut.model_validate(data))
    return BenchmarkRunResponse(
        id=run.id,
        document_id=run.document_id or "",
        created_at=run.created_at,
        config_results=results,
        injection_block_rate=run.production_recommendation.get("injection_block_rate"),
        pii_leak_count=run.production_recommendation.get("pii_leak_count"),
        recommended_config=run.production_recommendation.get("name"),
        harness_version=run.harness_version,
        dataset_id=run.dataset_id,
        dataset_version=run.dataset_version,
        n_items=run.n_items,
        run_config=run.run_config,
        duration_ms=run.duration_ms,
    )


def _validate_strategies(configs: list[str] | None) -> None:
    try:
        for name in configs or []:
            get_strategy(name)
    except UnknownStrategyError as exc:
        raise AppError("invalid_strategy", str(exc), 422) from exc


@router.post(
    "/documents/{document_id}/eval/datasets/generate", response_model=GenerateDatasetResponse
)
async def generate_dataset_route(
    document_id: str, body: GenerateDatasetRequest
) -> GenerateDatasetResponse:
    try:
        dataset = await service.generate_and_save_dataset(document_id, body.target_size)
    except service.EvaluationError as exc:
        raise AppError(exc.code, exc.message, 422) from exc

    categories: dict[str, int] = {}
    for item in load_dataset(dataset.path):
        categories[item.category] = categories.get(item.category, 0) + 1

    return GenerateDatasetResponse(
        dataset_id=dataset.id,
        document_id=dataset.document_id,
        version=dataset.version,
        item_count=dataset.item_count,
        categories=categories,
    )


@router.get("/documents/{document_id}/eval/datasets", response_model=DatasetListResponse)
async def list_datasets_route(document_id: str) -> DatasetListResponse:
    """Newest first."""
    rows = await service.list_datasets(document_id)
    return DatasetListResponse(datasets=[DatasetOut.model_validate(r) for r in rows])


@router.post(
    "/eval/benchmarks/run",
    response_model=BenchmarkRunResponse,
    dependencies=[Depends(limit_client("evaluation"))],
)
async def run_benchmark_route(body: RunBenchmarkRequest) -> BenchmarkRunResponse:
    """Runs to completion before answering. For scripts and tests; the UI uses /start."""
    _validate_strategies(body.configs)
    try:
        run, _report = await service.run_and_save_benchmark(
            body.document_id,
            body.configs,
            body.dataset_target_size,
            dataset_id=body.dataset_id,
            include_safety=body.include_safety,
        )
    except service.EvaluationError as exc:
        raise AppError(exc.code, exc.message, 422) from exc
    return benchmark_run_response(run)


@router.post(
    "/eval/benchmarks/start",
    response_model=StartedJob,
    dependencies=[Depends(limit_client("evaluation"))],
)
async def start_benchmark_route(body: RunBenchmarkRequest) -> StartedJob:
    """Starts the run as a background job. Follow it at /jobs/{job_id}/stream; its result
    carries the benchmark run id."""
    _validate_strategies(body.configs)
    job = await jobs.create_job("benchmark", body.model_dump())

    async def work(ctx: jobs.JobContext) -> dict:
        run, _report = await service.run_and_save_benchmark(
            body.document_id,
            body.configs,
            body.dataset_target_size,
            dataset_id=body.dataset_id,
            include_safety=body.include_safety,
            progress=ctx.progress,
            checkpoint=ctx.checkpoint,
        )
        return {"benchmark_run_id": run.id}

    jobs.launch(job.id, work)
    return StartedJob(job_id=job.id)


@router.get("/eval/benchmarks", response_model=BenchmarkRunListResponse)
async def list_all_benchmark_runs_route(limit: int = 30) -> BenchmarkRunListResponse:
    runs = await service.list_benchmark_runs(None, limit=max(1, min(limit, 100)))
    return BenchmarkRunListResponse(
        runs=[benchmark_run_response(r, include_samples=False) for r in runs]
    )


@router.get("/eval/benchmarks/{run_id}", response_model=BenchmarkRunResponse)
async def get_benchmark_route(run_id: str) -> BenchmarkRunResponse:
    run = await service.get_benchmark_run(run_id)
    if run is None:
        raise AppError("benchmark_not_found", f"No benchmark run with id {run_id}", 404)
    return benchmark_run_response(run)


@router.get("/documents/{document_id}/eval/benchmarks", response_model=BenchmarkRunListResponse)
async def list_benchmark_runs_route(document_id: str) -> BenchmarkRunListResponse:
    runs = await service.list_benchmark_runs(document_id)
    return BenchmarkRunListResponse(
        runs=[benchmark_run_response(r, include_samples=False) for r in runs]
    )
