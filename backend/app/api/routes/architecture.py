"""GET /api/v1/architecture/graph — the system's real topology, built by
app/core/topology.py from the packages that exist, the compiled agent graph, live health
probes and current configuration. The frontend renders whatever this returns; it holds no
node list, labels or positions of its own.
"""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter

from app.api.schemas.architecture import (
    ArchitectureEdgeOut,
    ArchitectureGraphOut,
    ArchitectureNodeOut,
    ArchitectureStageOut,
    NodeEventOut,
    NodeEventsOut,
)
from app.core import health, topology
from app.core.errors import AppError
from app.core.tracing import trace_bus

router = APIRouter(prefix="/architecture", tags=["architecture"])


@router.get("/graph", response_model=ArchitectureGraphOut)
async def get_architecture_graph() -> ArchitectureGraphOut:
    probes = await health.run_probes()
    built = topology.build_topology(probes)
    return ArchitectureGraphOut(
        generated_at=datetime.now(UTC).isoformat(),
        stats_since=trace_bus.started_at.isoformat(),
        stages=[ArchitectureStageOut(**s) for s in topology.STAGES],
        nodes=[ArchitectureNodeOut(**n) for n in built.nodes],
        edges=[ArchitectureEdgeOut(**e) for e in built.edges],
        stage_to_node=built.stage_to_node,
    )


@router.get("/nodes/{node_id}/events", response_model=NodeEventsOut)
async def get_node_events(node_id: str) -> NodeEventsOut:
    """The last 10 real trace events for a node, newest first (since the backend started)."""
    probes = await health.run_probes()
    node = next((n for n in topology.build_topology(probes).nodes if n["id"] == node_id), None)
    if node is None:
        raise AppError("node_not_found", f"No architecture node with id {node_id}", 404)
    events = trace_bus.recent_events(node["trace_stages"])
    return NodeEventsOut(
        node_id=node_id,
        events=[
            NodeEventOut(
                trace_id=e.trace_id,
                session_id=e.session_id,
                seq=e.seq,
                stage=e.stage,
                status=str(e.status),
                started_at=e.started_at.isoformat(),
                duration_ms=e.duration_ms,
                input_preview=e.input_preview,
                output_preview=e.output_preview,
                metrics=e.metrics,
            )
            for e in events
        ],
    )
