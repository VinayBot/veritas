from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class ArchitectureStageOut(BaseModel):
    id: int
    label: str
    description: str


class ArchitectureNodeOut(BaseModel):
    id: str
    label: str
    """Real module behind the node ("app.retrieval"); the browser client carries a source
    directory instead. Never a placeholder."""
    module_path: str
    one_line_purpose: str
    """1-5, the stage of the five-stage story this node belongs to; None for a package that
    exists in code but has not been placed."""
    stage: int | None
    """Id of the group this node sits inside (the agent's LangGraph nodes sit in "agents")."""
    parent: str | None
    """False for a package discovered in code that the manifest does not describe yet."""
    documented: bool
    status: str  # healthy | degraded | down | disabled | not_configured
    status_detail: str
    """What kind of check produced `status`: "dependency", "functional", "config", "trace"
    or "import" (the weakest — the module merely imports)."""
    probe_kind: str
    probe_id: str | None
    trace_stages: list[str]
    """Since the backend started; the trace bus is in memory."""
    invocation_count: int
    error_count: int
    last_latency_ms: float | None
    last_at: str | None
    p50_latency_ms: float | None
    p95_latency_ms: float | None
    latency_sample_size: int
    config: dict[str, Any]
    """Repo-relative and absolute path of the code behind the node."""
    source_path: str
    source_abs_path: str


class ArchitectureEdgeOut(BaseModel):
    id: str
    source: str
    target: str
    kind: str  # request | data | trace | optional
    label: str
    """"langgraph" for edges read off the compiled agent graph, "declared" for cross-module
    flow declared in app/core/topology.py and verified against real imports."""
    derived: str


class ArchitectureGraphOut(BaseModel):
    generated_at: str
    """Per-node counts and latencies cover the time since this moment."""
    stats_since: str
    stages: list[ArchitectureStageOut]
    nodes: list[ArchitectureNodeOut]
    edges: list[ArchitectureEdgeOut]
    """Trace stage name -> node id, so a live trace event can be placed on the diagram."""
    stage_to_node: dict[str, str]


class NodeEventOut(BaseModel):
    trace_id: str
    session_id: str
    seq: int
    stage: str
    status: str
    started_at: str
    duration_ms: float | None
    input_preview: str | None
    output_preview: str | None
    metrics: dict[str, Any]


class NodeEventsOut(BaseModel):
    node_id: str
    events: list[NodeEventOut]
