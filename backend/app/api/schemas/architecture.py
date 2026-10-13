from __future__ import annotations

from pydantic import BaseModel


class ArchitectureNodeOut(BaseModel):
    id: str
    label: str
    """Real module path backing this node, e.g. "app.agents.orchestrator" — frontend-only
    nodes (the browser) carry a source file path instead. Never a placeholder string."""
    module_path: str
    """Group-box membership for the System Design view: "indexes" | "council" | "workers" |
    None (not grouped)."""
    group: str | None = None
    """1-5, matching the light-flow stage this node participates in (Upload & Deliver,
    Refine & Protect, Understand, Retrieve & Reason, Answer & Celebrate). None for a node that
    sits outside the 5-stage narrative (e.g. the evaluator, run independently of a chat turn)."""
    stage: int | None = None
    """True only for a conceptual slot with no real code behind it yet. The frontend renders
    these with a dashed outline and never lets light reach them."""
    planned: bool = False


class ArchitectureEdgeOut(BaseModel):
    source: str
    target: str
    bidirectional: bool = True
    label: str | None = None
    stage: int | None = None


class ArchitectureTopologyOut(BaseModel):
    nodes: list[ArchitectureNodeOut]
    edges: list[ArchitectureEdgeOut]
