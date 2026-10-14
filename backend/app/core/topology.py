"""The system's real topology, for GET /api/v1/architecture/graph.

What is derived and what is declared, stated plainly:

- **Nodes are discovered.** Every package under `app/` becomes a node. The manifest below
  only adds a human label, a one-line purpose and a stage to a package that already exists;
  a manifest entry whose module is gone produces no node, and a package with no manifest
  entry still appears (marked undocumented). Delete or add a backend package and the
  diagram changes with no frontend edit.
- **The agent graph is introspected.** Its nodes and edges come from the compiled LangGraph
  (`get_agent_graph().get_graph()`), including which edges are conditional.
- **Cross-module edges are declared**, because data flow is implied by function calls and
  cannot be read off the code mechanically (import direction is not data-flow direction).
  Each declared edge names the call chain that carries it, and
  tests/test_architecture_api.py proves every link in that chain is a real import. An edge
  whose endpoint no longer exists is dropped.
- **Status and config are live**, from app/core/health.py probes and the current settings.
"""

from __future__ import annotations

import ast
import importlib
import importlib.util
import pkgutil
from collections.abc import Callable
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

import app as app_package
from app.core.config import get_settings
from app.core.health import ProbeResult
from app.core.tracing import trace_bus

APP_ROOT = Path(app_package.__file__).resolve().parent

STAGES: list[dict[str, Any]] = [
    {
        "id": 1,
        "label": "Ingest & Protect",
        "description": "A document is parsed, cleaned, and has its personal data masked "
        "before anything is stored.",
    },
    {
        "id": 2,
        "label": "Index",
        "description": "Text is chunked, embedded and written to the dense, keyword and "
        "graph indexes; the document is profiled.",
    },
    {
        "id": 3,
        "label": "Retrieve & Reason",
        "description": "A question is routed to a RAG strategy, evidence is retrieved, and "
        "models reason over it.",
    },
    {
        "id": 4,
        "label": "Verify",
        "description": "Guardrails check the input and output; evaluation measures quality.",
    },
    {
        "id": 5,
        "label": "Answer",
        "description": "The answer, its citations and the live trace stream back to the browser.",
    },
]


@dataclass(frozen=True)
class NodeSpec:
    id: str
    module_path: str
    label: str
    purpose: str
    stage: int | None
    """Trace stage names (app/core/tracing.py) this node is responsible for."""
    trace_stages: tuple[str, ...] = ()
    """Health probe id in app/core/health.py that backs this node's status, if any."""
    probe: str | None = None
    parent: str | None = None
    config: Callable[[], dict[str, Any]] | None = None
    """Optional adapters report not_configured (not "down") when they are simply not in use."""
    optional_when: Callable[[], str | None] | None = None


def _cfg_ingestion() -> dict[str, Any]:
    from app.ingestion.registry import supported_extensions

    return {"formats": len(supported_extensions()), "max_upload_mb": 25}


def _cfg_privacy() -> dict[str, Any]:
    settings = get_settings()
    return {
        "detector": "presidio + spaCy",
        "vault_key": "set" if settings.pii_vault_key else "dev default (not for production)",
    }


def _cfg_chunking() -> dict[str, Any]:
    from app.chunking.registry import (
        BASELINE_OVERLAP,
        BASELINE_SIZE,
        BASELINE_STRATEGY,
        supported_strategies,
    )

    return {
        "baseline": f"{BASELINE_STRATEGY} {BASELINE_SIZE}/{BASELINE_OVERLAP}",
        "strategies": supported_strategies(),
    }


def _cfg_embeddings() -> dict[str, Any]:
    from app.embeddings.registry import loaded_embedder_names
    from app.llm.models_config import get_model_config

    name = get_model_config().embedding
    return {"model": name, "loaded": name in loaded_embedder_names()}


def _cfg_retrieval() -> dict[str, Any]:
    from app.llm.models_config import get_model_config
    from app.retrieval.hybrid import RRF_K
    from app.retrieval.semantic_cache import SIMILARITY_THRESHOLD, size

    settings = get_settings()
    return {
        "pipeline": "RRF → rerank → HyDE (optional) → MMR",
        "rrf_k": RRF_K,
        "reranker": get_model_config().reranker,
        "semantic_cache": (
            f"on, {size()} entries, threshold {SIMILARITY_THRESHOLD}"
            if settings.semantic_cache_enabled
            else "off"
        ),
    }


def _cfg_llm() -> dict[str, Any]:
    from app.llm.models_config import get_model_config

    config = get_model_config()
    settings = get_settings()
    return {
        "provider": config.provider,
        "generator": config.generator,
        "judge": config.judge,
        "cloud": [
            name
            for name, key in (("groq", settings.groq_api_key), ("gemini", settings.gemini_api_key))
            if key
        ]
        or "none configured",
        "latency_budget_ms": settings.model_router_latency_budget_ms,
    }


def _cfg_council() -> dict[str, Any]:
    from app.llm.models_config import get_model_config

    config = get_model_config()
    tier = get_settings().hardware_tier
    return {
        "members": config.council,
        "chairman": config.chairman,
        "execution": "sequential" if tier == "8gb" else "concurrent",
        "mode": "opt-in per question",
    }


def _cfg_guardrails() -> dict[str, Any]:
    from app.guardrails import injection
    from app.llm.models_config import get_model_config

    return {
        "layers": ["input", "retrieval", "output"],
        "guard_model": get_model_config().guard,
        "injection_classifier": injection.MODEL_NAME,
        "rate_limit_per_minute": get_settings().rate_limit_per_minute,
    }


def _cfg_evaluation() -> dict[str, Any]:
    from app.evaluation.benchmark import FAITHFULNESS_GATE, P95_LATENCY_SLA_MS
    from app.llm.models_config import get_model_config

    return {
        "judge": get_model_config().judge,
        "faithfulness_gate": FAITHFULNESS_GATE,
        "p95_latency_gate_ms": P95_LATENCY_SLA_MS,
    }


def _cfg_graph_store() -> dict[str, Any]:
    if get_settings().graph_store == "neo4j":
        return {"backend": "neo4j", "persistence": "Neo4j server at NEO4J_URI"}
    return {"backend": "networkx", "persistence": "pickle file under DATA_DIR"}


def _cfg_vector_store() -> dict[str, Any]:
    backend = get_settings().vector_store
    return {"backend": backend, "distance": "cosine", "persistence": f"DATA_DIR/{backend}"}


def _cfg_bm25() -> dict[str, Any]:
    return {"library": "bm25s", "persistence": "in memory, rebuilt at startup"}


def _cfg_agents() -> dict[str, Any]:
    from app.agents.state import MAX_CRITIC_LOOPS, MAX_REVISE_LOOPS

    settings = get_settings()
    return {
        "max_critic_loops": MAX_CRITIC_LOOPS,
        "max_revise_loops": MAX_REVISE_LOOPS,
        "run_timeout_s": settings.run_timeout_seconds,
        "max_llm_calls_per_run": settings.max_llm_calls_per_run,
    }


def _cfg_core() -> dict[str, Any]:
    settings = get_settings()
    return {
        "hardware_tier": settings.hardware_tier,
        "database": settings.database_url.split(":", 1)[0].split("+", 1)[0],
        "env": settings.app_env,
    }


def _neo4j_optional() -> str | None:
    if get_settings().graph_store != "neo4j":
        return "GRAPH_STORE is not set to neo4j; the adapter exists but is not in use."
    return "GRAPH_STORE=neo4j is set, but the pipeline is wired to the NetworkX store only."


MANIFEST: list[NodeSpec] = [
    NodeSpec(
        "client",
        "frontend/src",
        "Browser client",
        "The React app: uploads documents, asks questions, renders the live trace.",
        5,
    ),
    NodeSpec(
        "api",
        "app.api",
        "API layer",
        "FastAPI routes, SSE chat stream and the trace WebSocket.",
        5,
        probe="database",
    ),
    NodeSpec(
        "ingestion",
        "app.ingestion",
        "Ingestion",
        "Parses files and URLs, repairs text quality, and runs the ingest job.",
        1,
        trace_stages=("upload", "parse", "refine"),
        config=_cfg_ingestion,
    ),
    NodeSpec(
        "privacy",
        "app.privacy",
        "PII vault",
        "Detects personal data, replaces it with tokens, stores the originals encrypted.",
        1,
        trace_stages=("pii_vault",),
        config=_cfg_privacy,
    ),
    NodeSpec(
        "chunking",
        "app.chunking",
        "Chunking",
        "Cuts masked text into passages using one of six strategies.",
        2,
        trace_stages=("chunk",),
        config=_cfg_chunking,
    ),
    NodeSpec(
        "embeddings",
        "app.embeddings",
        "Embeddings",
        "Turns text into vectors with a local sentence-transformers model.",
        2,
        trace_stages=("embed",),
        probe="embedder",
        config=_cfg_embeddings,
    ),
    NodeSpec(
        "stores.vector",
        "app.stores.vector",
        "Dense store (ChromaDB)",
        "Holds chunk vectors for search by meaning.",
        2,
        trace_stages=("index",),
        probe="chroma",
        config=_cfg_vector_store,
    ),
    NodeSpec(
        "stores.bm25",
        "app.stores.bm25",
        "Sparse store (BM25)",
        "Keyword index over every chunk.",
        2,
        probe="bm25",
        config=_cfg_bm25,
    ),
    NodeSpec(
        "graphrag",
        "app.graphrag",
        "GraphRAG",
        "Extracts entities and relations, resolves duplicates, answers by graph traversal.",
        2,
        trace_stages=("graph",),
    ),
    NodeSpec(
        "stores.graph",
        "app.stores.graph",
        "Graph store (NetworkX)",
        "Holds entities, relations and their communities.",
        2,
        probe="graph_store",
        config=_cfg_graph_store,
    ),
    NodeSpec(
        "stores.graph.neo4j",
        "app.stores.graph.neo4j_store",
        "Neo4j adapter",
        "Optional drop-in graph backend behind the same interface.",
        2,
        optional_when=_neo4j_optional,
    ),
    NodeSpec(
        "profiler",
        "app.profiler",
        "Profiler & chunking advisor",
        "Measures document features and runs the chunking tournament.",
        2,
        trace_stages=("profile", "advisor"),
    ),
    NodeSpec(
        "rag_engines",
        "app.rag_engines",
        "RAG strategy registry",
        "Named strategies composed from the retrieval building blocks, with a "
        "per-document recommendation.",
        3,
    ),
    NodeSpec(
        "retrieval",
        "app.retrieval",
        "Retrieval",
        "Dense + keyword search fused by rank, reranked, optionally HyDE-expanded and "
        "de-duplicated.",
        3,
        trace_stages=("retriever", "semantic_cache"),
        config=_cfg_retrieval,
    ),
    NodeSpec(
        "agents",
        "app.agents",
        "Agent (LangGraph)",
        "The orchestrator and the state machine that plans, retrieves, critiques, writes "
        "and verifies an answer.",
        3,
        probe="agent_graph",
        config=_cfg_agents,
    ),
    NodeSpec(
        "council",
        "app.council",
        "LLM council",
        "Several models answer independently, review each other anonymously, and a "
        "chairman writes the final answer.",
        3,
        trace_stages=("council",),
        probe="council",
        config=_cfg_council,
    ),
    NodeSpec(
        "llm",
        "app.llm",
        "LLM gateway",
        "One entry point to local Ollama models (and optional cloud ones), with per-query "
        "routing and a latency budget.",
        3,
        probe="ollama",
        config=_cfg_llm,
    ),
    NodeSpec(
        "guardrails",
        "app.guardrails",
        "Guardrails",
        "Checks the question, the retrieved text and the answer; logs every decision.",
        4,
        probe="guardrails",
        config=_cfg_guardrails,
    ),
    NodeSpec(
        "evaluation",
        "app.evaluation",
        "Evaluation",
        "Generates question sets from a document and scores strategies against them.",
        4,
        config=_cfg_evaluation,
    ),
    NodeSpec(
        "core",
        "app.core",
        "Core services",
        "Configuration, the metadata database, background jobs and the trace bus.",
        5,
        probe="trace_ws",
        config=_cfg_core,
    ),
]

AGENT_NODE_PURPOSE: dict[str, str] = {
    "guardian_in": "Runs the input guardrails before anything else.",
    "planner": "Classifies the question and picks the retrieval tools.",
    "decline": "Declines a question that is out of scope for the document.",
    "rewriter": "Rewrites the question for search; changes technique on each retry.",
    "retriever": "Runs the chosen tools and merges the evidence.",
    "critic": "Judges whether the evidence can answer the question; may send it back.",
    "summarizer": "Handles broad questions with wide retrieval and map-reduce.",
    "synthesizer": "Writes the cited answer, or asks the council to.",
    "verifier": "Checks each claim against the evidence; may ask for one revision.",
    "guardian_out": "Runs the output guardrails on the final answer.",
}


@dataclass(frozen=True)
class EdgeSpec:
    source: str
    target: str
    kind: str  # "request" | "data" | "trace" | "optional"
    label: str
    """Modules the call passes through between source and target. Every consecutive pair in
    [source, *via, target] must be linked by a real import (checked by the test suite).
    `"frontend"` endpoints are exempt — there is no Python import to check."""
    via: tuple[str, ...] = ()


AGENTS_ENTRY = "agents:entry"

DECLARED_EDGES: list[EdgeSpec] = [
    EdgeSpec("client", "api", "request", "HTTP · SSE"),
    EdgeSpec("api", "ingestion", "request", "upload / URL"),
    EdgeSpec("ingestion", "privacy", "data", "refined text"),
    EdgeSpec(
        "privacy",
        "chunking",
        "data",
        "masked text",
        via=("app.ingestion.service", "app.retrieval.indexing"),
    ),
    EdgeSpec("chunking", "embeddings", "data", "chunks", via=("app.retrieval.indexing",)),
    EdgeSpec("embeddings", "stores.vector", "data", "vectors", via=("app.retrieval.indexing",)),
    EdgeSpec("chunking", "stores.bm25", "data", "chunk text"),
    EdgeSpec("chunking", "graphrag", "data", "chunks"),
    EdgeSpec("graphrag", "stores.graph", "data", "entities · relations"),
    EdgeSpec("stores.graph", "stores.graph.neo4j", "optional", "alternative backend"),
    EdgeSpec("ingestion", "profiler", "data", "document text"),
    EdgeSpec("profiler", "evaluation", "data", "synthetic question set"),
    EdgeSpec("api", "agents.orchestrator", "request", "question + strategy"),
    EdgeSpec("agents.orchestrator", "rag_engines", "request", "strategy plan"),
    EdgeSpec("agents.orchestrator", AGENTS_ENTRY, "request", "agentic · council"),
    EdgeSpec("rag_engines", "retrieval", "request", "direct strategies"),
    EdgeSpec("agents.retriever", "retrieval", "request", "hybrid_search tool"),
    EdgeSpec("agents.retriever", "graphrag", "optional", "graph_traverse tool"),
    EdgeSpec("rag_engines", "graphrag", "optional", "graph strategy", via=("app.agents.tools",)),
    EdgeSpec("retrieval", "embeddings", "request", "embed query"),
    EdgeSpec("retrieval", "stores.vector", "request", "dense search"),
    EdgeSpec("retrieval", "stores.bm25", "request", "keyword search"),
    EdgeSpec("agents", "llm", "request", "plan · grade · write · verify"),
    EdgeSpec("agents.synthesizer", "council", "optional", "council mode"),
    EdgeSpec("council", "llm", "request", "member · review · chairman"),
    EdgeSpec("agents.guardian_in", "guardrails", "request", "input checks"),
    EdgeSpec("agents.guardian_out", "guardrails", "request", "output checks"),
    EdgeSpec("guardrails", "llm", "request", "Llama Guard"),
    EdgeSpec("guardrails", "privacy", "request", "PII redaction"),
    EdgeSpec("evaluation", "agents.orchestrator", "request", "benchmark questions"),
    EdgeSpec("evaluation", "llm", "request", "judge"),
    EdgeSpec("core", "api", "trace", "trace events"),
    EdgeSpec("api", "client", "trace", "/ws/trace"),
]


def module_exists(module_path: str) -> bool:
    if module_path.startswith("frontend"):
        return True
    try:
        return importlib.util.find_spec(module_path) is not None
    except (ImportError, ValueError):
        return False


def discovered_packages() -> list[str]:
    """Names of every package directly under app/ — the ground truth for which modules exist."""
    return sorted(m.name for m in pkgutil.iter_modules([str(APP_ROOT)]) if m.ispkg)


def _docstring_summary(module_path: str) -> str:
    try:
        module = importlib.import_module(module_path)
    except Exception:  # noqa: BLE001 — a module that fails to import still gets a node
        return "No description declared."
    doc = (module.__doc__ or "").strip()
    return doc.split("\n\n")[0].replace("\n", " ") if doc else "No description declared."


@lru_cache(maxsize=1)
def agent_graph_structure() -> dict[str, Any]:
    """Nodes and edges of the compiled LangGraph, with each node's defining module."""
    from app.agents.graph import get_agent_graph

    compiled = get_agent_graph()
    graph = compiled.get_graph()
    nodes: list[dict[str, str]] = []
    for name in graph.nodes:
        if name.startswith("__"):
            continue
        module_path = "app.agents.graph"
        spec = compiled.builder.nodes.get(name) if hasattr(compiled, "builder") else None
        runnable = getattr(spec, "runnable", None)
        fn = getattr(runnable, "afunc", None) or getattr(runnable, "func", None)
        if fn is not None and getattr(fn, "__module__", None):
            module_path = fn.__module__
        nodes.append({"name": name, "module_path": module_path})
    entry = next((e.target for e in graph.edges if e.source == "__start__"), None)
    exits = [e.source for e in graph.edges if e.target == "__end__"]
    edges = [
        {"source": e.source, "target": e.target, "conditional": bool(e.conditional)}
        for e in graph.edges
        if not e.source.startswith("__") and not e.target.startswith("__")
    ]
    return {"nodes": nodes, "edges": edges, "entry": entry, "exits": exits}


def _imports_of(path: Path) -> set[str]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (OSError, SyntaxError):
        return set()
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            found.add(node.module)
        elif isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
    return found


def _files_of(module_path: str) -> list[Path]:
    relative = Path(*module_path.split(".")[1:])
    as_package = APP_ROOT / relative
    if as_package.is_dir():
        return [p for p in as_package.rglob("*.py") if "__pycache__" not in p.parts]
    as_module = as_package.with_suffix(".py")
    return [as_module] if as_module.exists() else []


def imports_between(a: str, b: str) -> bool:
    """True when any file of module/package `a` imports `b` (or something under it), or the
    reverse — the evidence that two declared endpoints really are connected in code."""

    def one_way(src: str, dst: str) -> bool:
        return any(
            imported == dst or imported.startswith(dst + ".")
            for path in _files_of(src)
            for imported in _imports_of(path)
        )

    return one_way(a, b) or one_way(b, a)


REPO_ROOT = APP_ROOT.parents[1]


def _source_abs_path(module_path: str) -> str:
    if module_path.startswith("frontend"):
        return str(REPO_ROOT / module_path)
    relative = Path(*module_path.split(".")[1:])
    as_package = APP_ROOT / relative
    return str(as_package if as_package.is_dir() else as_package.with_suffix(".py"))


def _source_path(module_path: str) -> str:
    """Repo-relative path of the code behind a node — what the drawer's source link shows."""
    return str(Path(_source_abs_path(module_path)).relative_to(REPO_ROOT))


@dataclass
class Topology:
    nodes: list[dict[str, Any]] = field(default_factory=list)
    edges: list[dict[str, Any]] = field(default_factory=list)
    stage_to_node: dict[str, str] = field(default_factory=dict)


def _status_for(
    spec: NodeSpec | None,
    probes: dict[str, ProbeResult],
    stats: dict[str, Any] | None,
) -> tuple[str, str, str]:
    """(status, detail, probe_kind)."""
    if spec is not None and spec.optional_when is not None:
        reason = spec.optional_when()
        if reason:
            return "not_configured", reason, "config"
    if spec is not None and spec.probe and spec.probe in probes:
        probe = probes[spec.probe]
        detail = probe.detail + (f" — {probe.error}" if probe.error else "")
        return probe.status, detail, probe.kind
    if stats and stats.get("last_status") == "error":
        return "degraded", "Its most recent run ended in an error.", "trace"
    return "healthy", "Module imports cleanly; it has no external dependency to probe.", "import"


def _aggregate_stats(stages: tuple[str, ...]) -> dict[str, Any] | None:
    all_stats = trace_bus.stage_stats()
    picked = [all_stats[s] for s in stages if s in all_stats]
    if not picked:
        return None
    durations = sorted(d for s in picked for d in s.durations)
    latest = max(picked, key=lambda s: s.last_at or trace_bus.started_at)

    def pct(p: float) -> float | None:
        return durations[min(int(len(durations) * p), len(durations) - 1)] if durations else None

    return {
        "invocation_count": sum(s.count for s in picked),
        "error_count": sum(s.errors for s in picked),
        "last_latency_ms": latest.last_duration_ms,
        "last_status": latest.last_status,
        "last_at": latest.last_at.isoformat() if latest.last_at else None,
        "p50_latency_ms": pct(0.5),
        "p95_latency_ms": pct(0.95),
        "sample_size": len(durations),
    }


def _node_payload(
    node_id: str,
    module_path: str,
    label: str,
    purpose: str,
    stage: int | None,
    trace_stages: tuple[str, ...],
    spec: NodeSpec | None,
    probes: dict[str, ProbeResult],
    parent: str | None = None,
    documented: bool = True,
) -> dict[str, Any]:
    stats = _aggregate_stats(trace_stages)
    status, detail, probe_kind = _status_for(spec, probes, stats)
    config: dict[str, Any] = {}
    if spec is not None and spec.config is not None:
        try:
            config = spec.config()
        except Exception as exc:  # noqa: BLE001 — config display must not break the diagram
            config = {"error": f"{type(exc).__name__}: {exc}"}
    return {
        "id": node_id,
        "label": label,
        "module_path": module_path,
        "one_line_purpose": purpose,
        "stage": stage,
        "parent": parent,
        "documented": documented,
        "status": status,
        "status_detail": detail,
        "probe_kind": probe_kind,
        "probe_id": spec.probe if spec else None,
        "trace_stages": list(trace_stages),
        "invocation_count": stats["invocation_count"] if stats else 0,
        "error_count": stats["error_count"] if stats else 0,
        "last_latency_ms": stats["last_latency_ms"] if stats else None,
        "last_at": stats["last_at"] if stats else None,
        "p50_latency_ms": stats["p50_latency_ms"] if stats else None,
        "p95_latency_ms": stats["p95_latency_ms"] if stats else None,
        "latency_sample_size": stats["sample_size"] if stats else 0,
        "config": config,
        "source_path": _source_path(module_path),
        "source_abs_path": _source_abs_path(module_path),
    }


def build_topology(probes: list[ProbeResult]) -> Topology:
    probe_map = {p.id: p for p in probes}
    topology = Topology()
    node_ids: set[str] = set()

    for spec in MANIFEST:
        if not module_exists(spec.module_path):
            continue
        topology.nodes.append(
            _node_payload(
                spec.id,
                spec.module_path,
                spec.label,
                spec.purpose,
                spec.stage,
                spec.trace_stages,
                spec,
                probe_map,
                parent=spec.parent,
            )
        )
        node_ids.add(spec.id)

    # Packages that exist in code but that nobody described in the manifest still show up.
    documented_roots = {
        spec.module_path.split(".")[1] for spec in MANIFEST if "." in spec.module_path
    }
    for name in discovered_packages():
        if name in documented_roots:
            continue
        topology.nodes.append(
            _node_payload(
                name,
                f"app.{name}",
                name.replace("_", " ").title(),
                _docstring_summary(f"app.{name}"),
                None,
                (),
                None,
                probe_map,
                documented=False,
            )
        )
        node_ids.add(name)

    agent_exits: list[str] = []
    if "agents" in node_ids:
        agents_spec = next(s for s in MANIFEST if s.id == "agents")
        if module_exists("app.agents.orchestrator"):
            topology.nodes.append(
                _node_payload(
                    "agents.orchestrator",
                    "app.agents.orchestrator",
                    "Orchestrator",
                    "Entry point for a chat turn: cache check, strategy dispatch, timeout, "
                    "retry and the persisted report.",
                    3,
                    (),
                    None,
                    probe_map,
                    parent="agents",
                )
            )
            node_ids.add("agents.orchestrator")
        try:
            structure = agent_graph_structure()
        except Exception:  # noqa: BLE001 — the agent probe reports why; the rest still renders
            structure = {"nodes": [], "edges": [], "entry": None, "exits": []}
        for item in structure["nodes"]:
            name = item["name"]
            node_id = f"agents.{name}"
            topology.nodes.append(
                _node_payload(
                    node_id,
                    item["module_path"],
                    name.replace("_", " ").title(),
                    AGENT_NODE_PURPOSE.get(name, "A node of the agent state machine."),
                    4 if name in ("guardian_in", "guardian_out", "verifier") else 3,
                    (name,),
                    NodeSpec(node_id, item["module_path"], name, "", 3, probe=agents_spec.probe),
                    probe_map,
                    parent="agents",
                )
            )
            node_ids.add(node_id)
        for edge in structure["edges"]:
            topology.edges.append(
                {
                    "id": f"agents.{edge['source']}->agents.{edge['target']}",
                    "source": f"agents.{edge['source']}",
                    "target": f"agents.{edge['target']}",
                    "kind": "optional" if edge["conditional"] else "data",
                    "label": "conditional" if edge["conditional"] else "",
                    "derived": "langgraph",
                }
            )
        entry = structure.get("entry")
        agent_exits = [f"agents.{name}" for name in structure.get("exits", [])]
        entry_id = f"agents.{entry}" if entry else None
    else:
        entry_id = None

    for spec_edge in DECLARED_EDGES:
        source = spec_edge.source
        target = entry_id if spec_edge.target == AGENTS_ENTRY else spec_edge.target
        if target is None or source not in node_ids or target not in node_ids:
            continue
        topology.edges.append(
            {
                "id": f"{source}->{target}",
                "source": source,
                "target": target,
                "kind": spec_edge.kind,
                "label": spec_edge.label,
                "derived": "declared",
            }
        )
    for exit_id in agent_exits:
        if exit_id in node_ids and "api" in node_ids:
            topology.edges.append(
                {
                    "id": f"{exit_id}->api",
                    "source": exit_id,
                    "target": "api",
                    "kind": "data",
                    "label": "answer · citations",
                    "derived": "langgraph",
                }
            )

    for node in topology.nodes:
        for stage_name in node["trace_stages"]:
            topology.stage_to_node.setdefault(stage_name, node["id"])
    # Trace events name the browser as "client" in from_stage/to_stage (the first hop in and
    # the last hop out), so it needs a place on the diagram too.
    if "client" in node_ids:
        topology.stage_to_node.setdefault("client", "client")
    return topology
