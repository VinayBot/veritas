from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class IndexVariant:
    """An alternative chunking of a document, kept alongside its working index."""

    id: str
    chunker: str
    kwargs: dict[str, Any] = field(default_factory=dict)
    description: str = ""


@dataclass(frozen=True)
class RetrievalPlan:
    """How a direct (non-agentic) strategy finds evidence. Every field maps onto an existing
    argument of app/retrieval/service.search or the graph traversal tool."""

    variant: str = "default"
    mode: str = "hybrid"  # "dense" | "bm25" | "hybrid"
    rerank: bool = False
    hyde: bool = False
    dedupe: str | None = None  # "mmr" | "cosine" | "ngram"
    graph: bool = False
    k: int = 5


@dataclass(frozen=True)
class StrategySpec:
    id: str
    display_name: str
    description: str
    best_for: str
    components: tuple[str, ...]
    kind: str  # "direct" | "agentic"
    plan: RetrievalPlan | None
    council: bool
    """A declared starting estimate, shown as Estimated until this machine has measured
    runs of its own to replace it."""
    typical_latency_ms: int
    relative_cost: str  # "low" | "medium" | "high" | "very_high"
    min_hardware_tier: str  # "8gb" | "16gb"
    """Document or question traits this strategy suits; the advisor's rules refer to these."""
    suited_for: tuple[str, ...]
    """Rough count of generation-model calls for one answer, excluding quality scoring."""
    llm_calls: int = 1
