from __future__ import annotations

from fastapi import APIRouter

from app.api.schemas.evaluation import (
    BenchmarkRunListResponse,
    BenchmarkRunResponse,
    ConfigResultOut,
    GenerateDatasetRequest,
    GenerateDatasetResponse,
    RunBenchmarkRequest,
)
from app.core.errors import AppError
from app.evaluation import service
from app.evaluation.datasets import load_dataset
from app.evaluation.models import BenchmarkRun

router = APIRouter(tags=["evaluation"])


def _benchmark_run_response(run: BenchmarkRun) -> BenchmarkRunResponse:
    return BenchmarkRunResponse(
        id=run.id,
        document_id=run.document_id or "",
        config_results=[ConfigResultOut.model_validate(r) for r in run.config_results],
        injection_block_rate=run.production_recommendation.get("injection_block_rate", 0.0),
        pii_leak_count=run.production_recommendation.get("pii_leak_count", 0),
        recommended_config=run.production_recommendation.get("name"),
    )


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


@router.post("/eval/benchmarks/run", response_model=BenchmarkRunResponse)
async def run_benchmark_route(body: RunBenchmarkRequest) -> BenchmarkRunResponse:
    try:
        run, _report = await service.run_and_save_benchmark(
            body.document_id, body.configs, body.dataset_target_size
        )
    except service.EvaluationError as exc:
        raise AppError(exc.code, exc.message, 422) from exc

    return _benchmark_run_response(run)


@router.get("/eval/benchmarks/{run_id}", response_model=BenchmarkRunResponse)
async def get_benchmark_route(run_id: str) -> BenchmarkRunResponse:
    run = await service.get_benchmark_run(run_id)
    if run is None:
        raise AppError("benchmark_not_found", f"No benchmark run with id {run_id}", 404)

    return _benchmark_run_response(run)


@router.get("/documents/{document_id}/eval/benchmarks", response_model=BenchmarkRunListResponse)
async def list_benchmark_runs_route(document_id: str) -> BenchmarkRunListResponse:
    runs = await service.list_benchmark_runs(document_id)
    return BenchmarkRunListResponse(runs=[_benchmark_run_response(r) for r in runs])
