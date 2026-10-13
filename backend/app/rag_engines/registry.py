"""The strategy registry: what exists, in the order the UI lists it."""

from __future__ import annotations

from app.core import runtime_settings
from app.rag_engines.base import IndexVariant, RetrievalPlan, StrategySpec

INDEX_VARIANTS: dict[str, IndexVariant] = {
    "fixed_512": IndexVariant(
        "fixed_512",
        "fixed",
        {"size": 512, "overlap": 64},
        "Fixed 512-token chunks with a 64-token overlap",
    ),
    "semantic": IndexVariant(
        "semantic",
        "semantic",
        {"threshold": 0.5, "max_size": 512},
        "Chunks split where the meaning of consecutive sentences shifts",
    ),
}

_STRATEGIES: tuple[StrategySpec, ...] = (
    StrategySpec(
        id="naive",
        display_name="Naive",
        description="Fixed-size chunks, search by meaning only, take the top results.",
        best_for="A baseline, or when speed matters most",
        components=("fixed-size chunks", "dense search", "top-k"),
        kind="direct",
        plan=RetrievalPlan(variant="fixed_512", mode="dense"),
        council=False,
        typical_latency_ms=4_000,
        relative_cost="low",
        min_hardware_tier="8gb",
        suited_for=("short_document", "simple_lookup", "speed"),
    ),
    StrategySpec(
        id="hybrid",
        display_name="Hybrid",
        description="Search by meaning and by keyword, then merge the two rankings.",
        best_for="General-purpose questions",
        components=("recursive chunks", "dense search", "BM25", "rank fusion"),
        kind="direct",
        plan=RetrievalPlan(mode="hybrid"),
        council=False,
        typical_latency_ms=4_500,
        relative_cost="low",
        min_hardware_tier="8gb",
        suited_for=("general", "mixed_vocabulary"),
    ),
    StrategySpec(
        id="hybrid_rerank",
        display_name="Hybrid + Rerank",
        description="Hybrid search, then a second model re-reads the candidates and drops "
        "near-duplicates.",
        best_for="When precision matters",
        components=("recursive chunks", "dense search", "BM25", "rank fusion", "rerank", "MMR"),
        kind="direct",
        plan=RetrievalPlan(mode="hybrid", rerank=True, dedupe="mmr"),
        council=False,
        typical_latency_ms=5_500,
        relative_cost="low",
        min_hardware_tier="8gb",
        suited_for=("general", "precision", "long_document", "structured"),
    ),
    StrategySpec(
        id="hyde",
        display_name="HyDE",
        description="The model first drafts a guess at the answer and searches with that, "
        "then hybrid search and rerank.",
        best_for="Vague or very short questions",
        components=("HyDE query expansion", "hybrid search", "rerank"),
        kind="direct",
        plan=RetrievalPlan(mode="hybrid", rerank=True, hyde=True),
        council=False,
        typical_latency_ms=9_000,
        relative_cost="medium",
        min_hardware_tier="8gb",
        suited_for=("vague_question", "short_question"),
        llm_calls=2,
    ),
    StrategySpec(
        id="semantic_chunk",
        display_name="Semantic chunks",
        description="Chunks follow shifts in meaning instead of a fixed size, then hybrid "
        "search and rerank.",
        best_for="Long prose and essays",
        components=("semantic chunking", "hybrid search", "rerank"),
        kind="direct",
        plan=RetrievalPlan(variant="semantic", mode="hybrid", rerank=True),
        council=False,
        typical_latency_ms=5_500,
        relative_cost="low",
        min_hardware_tier="8gb",
        suited_for=("prose", "long_document", "low_structure"),
    ),
    StrategySpec(
        id="graph_rag",
        display_name="GraphRAG",
        description="Follows relations between entities in the knowledge graph, alongside "
        "hybrid search.",
        best_for="Multi-hop questions and entity-dense documents",
        components=("entity + relation extraction", "graph traversal", "hybrid search", "rerank"),
        kind="direct",
        plan=RetrievalPlan(mode="hybrid", rerank=True, graph=True),
        council=False,
        typical_latency_ms=6_500,
        relative_cost="medium",
        min_hardware_tier="8gb",
        suited_for=("entity_dense", "multi_hop", "cross_referenced"),
    ),
    StrategySpec(
        id="agentic",
        display_name="Agentic",
        description="A planner, retriever, critic, writer and verifier work in a loop, "
        "retrying when the evidence is thin.",
        best_for="Complex, multi-part questions",
        components=("planner", "rewriter", "retriever", "critic", "synthesizer", "verifier"),
        kind="agentic",
        plan=None,
        council=False,
        typical_latency_ms=30_000,
        relative_cost="high",
        min_hardware_tier="8gb",
        suited_for=("multi_part_question", "multi_hop", "needs_verification"),
        llm_calls=7,
    ),
    StrategySpec(
        id="council",
        display_name="Council",
        description="The agentic loop, with several models answering independently, "
        "reviewing each other, and a chairman writing the final answer.",
        best_for="High-stakes answers that need consensus",
        components=("agentic loop", "multi-model council", "peer review", "chairman"),
        kind="agentic",
        plan=None,
        council=True,
        typical_latency_ms=90_000,
        relative_cost="very_high",
        min_hardware_tier="16gb",
        suited_for=("high_stakes", "needs_consensus"),
        llm_calls=14,
    ),
)

STRATEGIES: dict[str, StrategySpec] = {s.id: s for s in _STRATEGIES}

# The out-of-the-box default: one retrieval pass and one generation, so a normal question
# gets a quick answer. The agentic loop is there when a question needs it.
FALLBACK_DEFAULT = "hybrid_rerank"

# What chat reports written before strategies existed recorded in their `mode` column.
LEGACY_MODES: dict[str, str] = {
    "agentic": "agentic",
    "hybrid": "hybrid_rerank",
    "graph": "graph_rag",
}


class UnknownStrategyError(ValueError):
    pass


def list_strategies() -> list[StrategySpec]:
    return list(_STRATEGIES)


def get_strategy(strategy_id: str) -> StrategySpec:
    try:
        return STRATEGIES[strategy_id]
    except KeyError:
        raise UnknownStrategyError(
            f"Unknown RAG strategy: {strategy_id!r}. Known: {sorted(STRATEGIES)}"
        ) from None


def default_strategy_id() -> str:
    chosen = runtime_settings.current().get("default_strategy")
    return chosen if chosen in STRATEGIES else FALLBACK_DEFAULT


async def set_default_strategy(strategy_id: str) -> None:
    get_strategy(strategy_id)
    await runtime_settings.set_value("default_strategy", strategy_id)


def strategy_for_report(strategy: str | None, legacy_mode: str | None) -> str:
    """The strategy a stored chat report used, including ones written before the registry."""
    if strategy in STRATEGIES:
        return str(strategy)
    return LEGACY_MODES.get(legacy_mode or "", legacy_mode or "unknown")
