"""GET /api/v1/architecture/topology — the real system-component inventory behind the
Architecture tab's System Design diagram: node ids, their real backing module path, which
light-flow stage (1-5) and group box (if any) they belong to, and the edges between them.

This is additive and read-only: it does not touch ingestion/chat/retrieval behaviour, only
describes it. The frontend's hand-authored layout/icon assignment (architectureLayout.ts) is
checked against this list by a vitest contract test — every non-planned node here must have a
layout entry, and vice versa, so the diagram can never silently drift from the real system."""

from __future__ import annotations

from fastapi import APIRouter

from app.api.schemas.architecture import (
    ArchitectureEdgeOut,
    ArchitectureNodeOut,
    ArchitectureTopologyOut,
)

router = APIRouter(prefix="/architecture", tags=["architecture"])

_NODES: list[ArchitectureNodeOut] = [
    ArchitectureNodeOut(id="user", label="Users", module_path="frontend/src/pages/workspace-page.tsx"),
    ArchitectureNodeOut(id="gateway", label="API Gateway", module_path="app.main", stage=1),
    ArchitectureNodeOut(
        id="guardrails_in", label="Guardrails In", module_path="app.guardrails.input", stage=4
    ),
    ArchitectureNodeOut(id="router", label="Mode Router", module_path="app.api.routes.chat", stage=4),
    ArchitectureNodeOut(
        id="orchestrator", label="Orchestrator", module_path="app.agents.orchestrator", stage=4
    ),
    ArchitectureNodeOut(id="event_bus", label="Trace Event Bus", module_path="app.core.tracing", stage=5),
    ArchitectureNodeOut(id="llm_providers", label="LLM Providers", module_path="app.llm.client", stage=4),
    ArchitectureNodeOut(
        id="index_manager", label="Retrieval Manager", module_path="app.retrieval.service", stage=4
    ),
    ArchitectureNodeOut(id="metadb", label="Metadata DB", module_path="app.core.db", stage=2),
    ArchitectureNodeOut(id="cache", label="Semantic Cache", module_path="app.retrieval.semantic_cache", stage=4),
    ArchitectureNodeOut(id="pii_vault", label="PII Vault", module_path="app.privacy.vault", stage=2),
    ArchitectureNodeOut(
        id="trace_ids", label="Trace ID Issuer", module_path="app.core.tracing", stage=4
    ),
    ArchitectureNodeOut(
        id="ingest_scheduler", label="Ingestion Scheduler", module_path="app.ingestion.service", stage=1
    ),
    ArchitectureNodeOut(id="evaluator", label="Evaluation Harness", module_path="app.evaluation.benchmark"),
    # group: indexes
    ArchitectureNodeOut(
        id="index_dense", label="Dense (ChromaDB)", module_path="app.stores.vector", group="indexes", stage=3
    ),
    ArchitectureNodeOut(
        id="index_sparse", label="Sparse (BM25)", module_path="app.stores.bm25", group="indexes", stage=3
    ),
    ArchitectureNodeOut(
        id="index_graph",
        label="Graph (NetworkX)",
        module_path="app.stores.graph.networkx_store",
        group="indexes",
        stage=3,
    ),
    # group: council
    ArchitectureNodeOut(
        id="council_member_1", label="Council Member A", module_path="app.council.service", group="council", stage=4
    ),
    ArchitectureNodeOut(
        id="council_member_2", label="Council Member B", module_path="app.council.service", group="council", stage=4
    ),
    ArchitectureNodeOut(
        id="council_chairman", label="Chairman", module_path="app.council.service", group="council", stage=4
    ),
    # group: workers
    ArchitectureNodeOut(
        id="worker_docling",
        label="Docling Parser",
        module_path="app.ingestion.parsers.docling_parser",
        group="workers",
        stage=1,
    ),
    ArchitectureNodeOut(
        id="worker_scraper", label="URL Scraper", module_path="app.ingestion.scraper", group="workers", stage=1
    ),
    ArchitectureNodeOut(
        id="worker_refiner", label="Refiner", module_path="app.ingestion.refiner", group="workers", stage=2
    ),
]

_EDGES: list[ArchitectureEdgeOut] = [
    ArchitectureEdgeOut(source="user", target="gateway", stage=1),
    ArchitectureEdgeOut(source="gateway", target="guardrails_in", stage=4),
    ArchitectureEdgeOut(source="gateway", target="router", stage=4),
    ArchitectureEdgeOut(source="gateway", target="ingest_scheduler", stage=1),
    ArchitectureEdgeOut(source="router", target="orchestrator", stage=4),
    ArchitectureEdgeOut(source="orchestrator", target="event_bus", stage=5),
    ArchitectureEdgeOut(
        source="event_bus", target="user", bidirectional=False, label="Notifications", stage=5
    ),
    ArchitectureEdgeOut(source="orchestrator", target="llm_providers", stage=4),
    ArchitectureEdgeOut(source="orchestrator", target="index_manager", stage=4),
    ArchitectureEdgeOut(source="index_manager", target="index_dense", stage=3),
    ArchitectureEdgeOut(source="index_manager", target="index_sparse", stage=3),
    ArchitectureEdgeOut(source="index_manager", target="index_graph", stage=3),
    ArchitectureEdgeOut(source="orchestrator", target="council_member_1", stage=4),
    ArchitectureEdgeOut(source="orchestrator", target="council_member_2", stage=4),
    ArchitectureEdgeOut(source="orchestrator", target="council_chairman", stage=4),
    ArchitectureEdgeOut(source="orchestrator", target="metadb", stage=2),
    ArchitectureEdgeOut(source="metadb", target="cache", stage=4),
    ArchitectureEdgeOut(source="metadb", target="pii_vault", stage=2),
    ArchitectureEdgeOut(source="pii_vault", target="event_bus", stage=2),
    ArchitectureEdgeOut(source="orchestrator", target="trace_ids", stage=4),
    ArchitectureEdgeOut(source="event_bus", target="ingest_scheduler", stage=1),
    ArchitectureEdgeOut(source="ingest_scheduler", target="worker_docling", stage=1),
    ArchitectureEdgeOut(source="ingest_scheduler", target="worker_scraper", stage=1),
    ArchitectureEdgeOut(source="ingest_scheduler", target="worker_refiner", stage=2),
    ArchitectureEdgeOut(
        source="worker_docling", target="pii_vault", bidirectional=False, stage=2
    ),
    ArchitectureEdgeOut(
        source="worker_refiner", target="index_manager", bidirectional=False, stage=3
    ),
    ArchitectureEdgeOut(source="evaluator", target="orchestrator"),
    ArchitectureEdgeOut(source="evaluator", target="ingest_scheduler"),
]


@router.get("/topology", response_model=ArchitectureTopologyOut)
async def get_architecture_topology() -> ArchitectureTopologyOut:
    return ArchitectureTopologyOut(nodes=_NODES, edges=_EDGES)
