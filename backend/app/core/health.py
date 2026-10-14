"""Per-subsystem health probes and the end-to-end self-check behind the Architecture tab.

Every status here comes from actually exercising the thing it describes: an HTTP call to
Ollama, a count against the vector store, compiling the agent graph. A probe that fails
returns the exact error rather than a generic "unhealthy", and each result says what kind of
check it was, so "healthy" never claims more than was verified.

Statuses:
- healthy         the check ran and passed
- degraded        it works, with a caveat that matters (a required model is missing, ...)
- down            the check failed
- disabled        present but switched off by configuration
- not_configured  optional and never set up — distinct from broken
"""

from __future__ import annotations

import asyncio
import time
import uuid
from collections import deque
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import httpx
from sqlalchemy import func, select, text

from app.core.config import get_settings
from app.core.db import session_scope
from app.core.tracing import trace_bus

LATENCY_WINDOW = 50
PROBE_TIMEOUT_SECONDS = 8.0
CACHE_SECONDS = 4.0

OLLAMA_START_HINT = "Start it with `ollama serve` (or open the Ollama app)."


@dataclass
class ProbeResult:
    id: str
    label: str
    status: str
    detail: str
    kind: str  # "dependency" | "functional" | "config"
    raw: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    fix: str | None = None
    latency_ms: float = 0.0
    p50_latency_ms: float | None = None
    checked_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "label": self.label,
            "status": self.status,
            "detail": self.detail,
            "kind": self.kind,
            "raw": self.raw,
            "error": self.error,
            "fix": self.fix,
            "latency_ms": round(self.latency_ms, 1),
            "p50_latency_ms": None
            if self.p50_latency_ms is None
            else round(self.p50_latency_ms, 1),
            "checked_at": self.checked_at,
        }


_latencies: dict[str, deque[float]] = {}
_cache: tuple[float, list[ProbeResult]] | None = None


def _models_named(configured: list[str]) -> list[str]:
    return sorted({m.removeprefix("ollama/") for m in configured if m.startswith("ollama/")})


async def ollama_inventory() -> dict[str, Any]:
    """Installed and currently-loaded Ollama models. Raises on any failure to reach Ollama."""
    settings = get_settings()
    async with httpx.AsyncClient(timeout=3.0) as client:
        tags = await client.get(f"{settings.ollama_base_url}/api/tags")
        tags.raise_for_status()
        ps = await client.get(f"{settings.ollama_base_url}/api/ps")
        ps.raise_for_status()
    return {
        "installed": [m["name"] for m in tags.json().get("models", [])],
        "loaded": [
            {"name": m["name"], "size_vram": m.get("size_vram"), "expires_at": m.get("expires_at")}
            for m in ps.json().get("models", [])
        ],
    }


async def _probe_ollama() -> ProbeResult:
    from app.llm.models_config import get_model_config

    config = get_model_config()
    if config.provider != "ollama" and not any(
        m.startswith("ollama/") for m in config.all_llm_models()
    ):
        return ProbeResult(
            "ollama",
            "Ollama",
            "disabled",
            f"LLM provider is {config.provider}; no local model is configured.",
            "config",
        )
    try:
        inventory = await ollama_inventory()
    except (httpx.HTTPError, KeyError, ValueError) as exc:
        return ProbeResult(
            "ollama",
            "Ollama",
            "down",
            f"Not reachable at {get_settings().ollama_base_url}",
            "dependency",
            error=f"{type(exc).__name__}: {exc}" or type(exc).__name__,
            fix=OLLAMA_START_HINT,
        )
    required = _models_named(config.all_llm_models())
    missing = [m for m in required if m not in inventory["installed"]]
    loaded = [m["name"] for m in inventory["loaded"]]
    raw = {**inventory, "required": required, "missing": missing}
    if missing:
        return ProbeResult(
            "ollama",
            "Ollama",
            "degraded",
            f"{len(inventory['installed'])} installed, {len(loaded)} loaded; "
            f"missing: {', '.join(missing)}",
            "dependency",
            raw=raw,
            fix="Pull it with `ollama pull " + missing[0] + "`.",
        )
    return ProbeResult(
        "ollama",
        "Ollama",
        "healthy",
        f"{len(inventory['installed'])} installed, {len(loaded)} loaded"
        + (f" ({', '.join(loaded)})" if loaded else ""),
        "dependency",
        raw=raw,
    )


async def _probe_chroma() -> ProbeResult:
    from app.stores.vector import get_vector_store

    store = get_vector_store()
    count = await asyncio.to_thread(store.count)
    return ProbeResult(
        "chroma",
        "ChromaDB",
        "healthy",
        f"{count} vectors in collection '{store.collection_name}'",
        "functional",
        raw={"collection": store.collection_name, "vectors": count},
    )


async def _probe_bm25() -> ProbeResult:
    from app.chunking.models import ChunkRow
    from app.stores.bm25 import get_bm25_index

    indexed = get_bm25_index().size()
    async with session_scope() as session:
        stored = (await session.execute(select(func.count()).select_from(ChunkRow))).scalar_one()
    raw = {"indexed_chunks": indexed, "chunks_in_database": int(stored)}
    if indexed == 0 and stored > 0:
        return ProbeResult(
            "bm25",
            "BM25 index",
            "degraded",
            f"The keyword index is empty but the database holds {stored} chunks — keyword "
            "search will return nothing.",
            "functional",
            raw=raw,
            fix="Restart the backend (the index is rebuilt at startup) or ingest any document.",
        )
    return ProbeResult(
        "bm25",
        "BM25 index",
        "healthy",
        f"{indexed} chunks indexed in memory",
        "functional",
        raw=raw,
    )


async def _probe_graph_store() -> ProbeResult:
    from app.stores.graph.networkx_store import get_graph_store

    store = get_graph_store()
    settings = get_settings()
    raw = {
        "backend": "networkx",
        "entities": store.node_count(),
        "relations": store.edge_count(),
        "configured_backend": settings.graph_store,
    }
    detail = f"NetworkX — {store.node_count()} entities, {store.edge_count()} relations"
    if settings.graph_store != "networkx":
        return ProbeResult(
            "graph_store",
            "Graph store",
            "degraded",
            detail + f". GRAPH_STORE={settings.graph_store} is set, but only the NetworkX "
            "store is wired into the pipeline, so that setting has no effect.",
            "functional",
            raw=raw,
        )
    return ProbeResult("graph_store", "Graph store", "healthy", detail, "functional", raw=raw)


async def _probe_agent_graph() -> ProbeResult:
    from app.agents.graph import get_agent_graph

    graph = await asyncio.to_thread(lambda: get_agent_graph().get_graph())
    nodes = [n for n in graph.nodes if not n.startswith("__")]
    return ProbeResult(
        "agent_graph",
        "LangGraph agent",
        "healthy",
        f"Compiled: {len(nodes)} nodes, {len(graph.edges)} edges",
        "functional",
        raw={"nodes": nodes, "edge_count": len(graph.edges)},
    )


async def _probe_council() -> ProbeResult:
    from app.llm.models_config import get_model_config

    config = get_model_config()
    members = config.council
    tier = get_settings().hardware_tier
    raw: dict[str, Any] = {
        "members": members,
        "chairman": config.chairman,
        "execution": "sequential" if tier == "8gb" else "concurrent",
    }
    if len(members) < 2:
        return ProbeResult(
            "council",
            "Council",
            "not_configured",
            f"{len(members)} council model configured; a council needs at least 2.",
            "config",
            raw=raw,
            fix="Add models to the council roster in Settings.",
        )
    try:
        installed = (await ollama_inventory())["installed"]
    except (httpx.HTTPError, KeyError, ValueError) as exc:
        return ProbeResult(
            "council",
            "Council",
            "down",
            "Cannot check council models: Ollama is unreachable.",
            "dependency",
            raw=raw,
            error=f"{type(exc).__name__}: {exc}",
            fix=OLLAMA_START_HINT,
        )
    missing = [m for m in _models_named([*members, config.chairman]) if m not in installed]
    raw["missing"] = missing
    if missing:
        return ProbeResult(
            "council",
            "Council",
            "degraded",
            f"Missing council model(s): {', '.join(missing)}",
            "dependency",
            raw=raw,
            fix="Pull it with `ollama pull " + missing[0] + "`.",
        )
    return ProbeResult(
        "council",
        "Council",
        "healthy",
        f"{len(members)} members + chairman installed; opt-in per question, runs "
        f"{raw['execution']} on the {tier} tier",
        "dependency",
        raw=raw,
    )


async def _probe_guardrails() -> ProbeResult:
    from app.guardrails import injection
    from app.llm.models_config import get_model_config

    guard = get_model_config().guard
    classifier_loaded = injection.classifier_loaded()
    raw: dict[str, Any] = {
        "guard_model": guard,
        "injection_classifier": injection.MODEL_NAME,
        "injection_classifier_loaded": classifier_loaded,
        "layers": ["input", "retrieval", "output"],
    }
    guard_ok = True
    if guard.startswith("ollama/"):
        try:
            installed = (await ollama_inventory())["installed"]
            guard_ok = guard.removeprefix("ollama/") in installed
        except (httpx.HTTPError, KeyError, ValueError):
            guard_ok = False
    raw["guard_model_available"] = guard_ok
    if not guard_ok:
        return ProbeResult(
            "guardrails",
            "Guardrails",
            "degraded",
            f"{guard} is unavailable, so the Llama Guard layer fails open. Regex and the "
            "injection classifier still run.",
            "dependency",
            raw=raw,
            fix="Start Ollama and `ollama pull " + guard.removeprefix("ollama/") + "`.",
        )
    return ProbeResult(
        "guardrails",
        "Guardrails",
        "healthy",
        "Regex + injection classifier"
        + (" (loaded)" if classifier_loaded else " (loads on first use)")
        + f" + {guard.removeprefix('ollama/')}",
        "dependency",
        raw=raw,
    )


async def _probe_embedder() -> ProbeResult:
    from app.embeddings.registry import get_embedder, loaded_embedder_names
    from app.llm.models_config import get_model_config

    name = get_model_config().embedding
    if name not in loaded_embedder_names():
        return ProbeResult(
            "embedder",
            "Embedder",
            "degraded",
            f"{name} is not loaded yet (it loads during startup warm-up or on first use).",
            "functional",
            raw={"model": name, "loaded": False},
        )
    embedder = get_embedder()
    return ProbeResult(
        "embedder",
        "Embedder",
        "healthy",
        f"{embedder.model_name} ({embedder.dimension}d) loaded",
        "functional",
        raw={"model": embedder.model_name, "dimension": embedder.dimension, "loaded": True},
    )


async def _probe_database() -> ProbeResult:
    async with session_scope() as session:
        await session.execute(text("SELECT 1"))
    return ProbeResult(
        "database", "Metadata DB", "healthy", "SQLite answered a query", "functional"
    )


async def _probe_trace_ws() -> ProbeResult:
    subscribers = trace_bus.subscriber_count()
    return ProbeResult(
        "trace_ws",
        "Trace WS",
        "healthy",
        f"Trace bus up: {subscribers} subscriber(s), {trace_bus.session_count()} session(s) "
        "since start. Whether this browser is connected is shown by the page itself.",
        "functional",
        raw={
            "subscribers": subscribers,
            "sessions": trace_bus.session_count(),
            "bus_started_at": trace_bus.started_at.isoformat(),
        },
    )


_PROBES: list[tuple[str, str, Callable[[], Awaitable[ProbeResult]]]] = [
    ("ollama", "Ollama", _probe_ollama),
    ("chroma", "ChromaDB", _probe_chroma),
    ("bm25", "BM25 index", _probe_bm25),
    ("graph_store", "Graph store", _probe_graph_store),
    ("agent_graph", "LangGraph agent", _probe_agent_graph),
    ("council", "Council", _probe_council),
    ("guardrails", "Guardrails", _probe_guardrails),
    ("trace_ws", "Trace WS", _probe_trace_ws),
    ("embedder", "Embedder", _probe_embedder),
    ("database", "Metadata DB", _probe_database),
]


async def _run_one(
    probe_id: str, label: str, fn: Callable[[], Awaitable[ProbeResult]]
) -> ProbeResult:
    start = time.perf_counter()
    try:
        result = await asyncio.wait_for(fn(), timeout=PROBE_TIMEOUT_SECONDS)
    except Exception as exc:  # noqa: BLE001 — a probe must report its failure, never raise it
        result = ProbeResult(
            probe_id,
            label,
            "down",
            "The check itself failed.",
            "functional",
            error=f"{type(exc).__name__}: {exc}" if str(exc) else type(exc).__name__,
        )
    result.latency_ms = (time.perf_counter() - start) * 1000
    window = _latencies.setdefault(probe_id, deque(maxlen=LATENCY_WINDOW))
    window.append(result.latency_ms)
    ordered = sorted(window)
    result.p50_latency_ms = ordered[len(ordered) // 2]
    result.checked_at = datetime.now(UTC).isoformat()
    return result


async def run_probes(force: bool = False) -> list[ProbeResult]:
    """All probes, concurrently. Results are reused for a few seconds so several panels
    polling at once cost one round of checks, not one each."""
    global _cache
    now = time.monotonic()
    if not force and _cache is not None and now - _cache[0] < CACHE_SECONDS:
        return _cache[1]
    results = list(await asyncio.gather(*(_run_one(i, label, fn) for i, label, fn in _PROBES)))
    _cache = (time.monotonic(), results)
    return results


def reset_cache() -> None:
    global _cache
    _cache = None


# ---- End-to-end self-check -------------------------------------------------------------


@dataclass
class SelfCheckStage:
    name: str
    label: str
    ok: bool
    duration_ms: float
    detail: str
    error: str | None = None


async def _timed(
    name: str, label: str, fn: Callable[[], Awaitable[str]], timeout: float
) -> SelfCheckStage:
    start = time.perf_counter()
    try:
        detail = await asyncio.wait_for(fn(), timeout=timeout)
        return SelfCheckStage(name, label, True, (time.perf_counter() - start) * 1000, detail)
    except Exception as exc:  # noqa: BLE001 — report it; the point is to show what broke
        message = f"{type(exc).__name__}: {exc}" if str(exc) else type(exc).__name__
        return SelfCheckStage(
            name, label, False, (time.perf_counter() - start) * 1000, "failed", error=message
        )


async def run_self_check() -> list[SelfCheckStage]:
    """A real pass through the pipeline's moving parts, in order: database, a tiny
    embedding, a dense search with that embedding, a keyword search, the graph store, a
    one-token generation, and a round trip through the trace bus. Stages run one after
    another so each timing is that stage alone."""
    from app.embeddings.registry import get_embedder
    from app.llm.models_config import get_model_config
    from app.stores.bm25 import get_bm25_index
    from app.stores.graph.networkx_store import get_graph_store
    from app.stores.vector import get_vector_store

    settings = get_settings()
    state: dict[str, Any] = {}

    async def database() -> str:
        async with session_scope() as session:
            await session.execute(text("SELECT 1"))
        return "SQLite answered SELECT 1"

    async def embed() -> str:
        embedder = get_embedder()
        state["vector"] = await asyncio.to_thread(embedder.embed_one, "veritas self-check probe")
        return f"{embedder.model_name} produced a {len(state['vector'])}-dimension vector"

    async def dense_search() -> str:
        if "vector" not in state:
            raise RuntimeError("skipped: no embedding was produced by the previous stage")
        hits = await asyncio.to_thread(get_vector_store().query, state["vector"], 3)
        if not hits:
            return "query ran; the collection is empty, so 0 results"
        return f"top-{len(hits)} returned, best similarity {hits[0].score:.3f}"

    async def keyword_search() -> str:
        index = get_bm25_index()
        hits = index.search("policy document", k=3)
        return f"query ran against {index.size()} indexed chunks, {len(hits)} result(s)"

    async def graph() -> str:
        store = get_graph_store()
        return f"{store.node_count()} entities, {store.edge_count()} relations"

    async def generate() -> str:
        model = get_model_config().generator
        if not model.startswith("ollama/"):
            from app.llm.client import complete

            text_out = await complete("Reply with: ok", model=model, max_tokens=1, timeout=30.0)
            return f"{model} returned {len(text_out)} character(s)"
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(
                f"{settings.ollama_base_url}/api/generate",
                json={
                    "model": model.removeprefix("ollama/"),
                    "prompt": "Reply with: ok",
                    "stream": False,
                    "options": {"num_predict": 1},
                },
            )
            resp.raise_for_status()
            body = resp.json()
        load_ms = body.get("load_duration", 0) / 1e6
        return (
            f"{model.removeprefix('ollama/')} generated {body.get('eval_count', 0)} token(s)"
            f" (model load {load_ms:.0f}ms)"
        )

    async def trace_round_trip() -> str:
        session_id = f"selfcheck-{uuid.uuid4()}"
        queue = trace_bus.subscribe(session_id)
        try:
            async with trace_bus.stage(session_id, "self_check") as handle:
                handle.set_output("probe")
            first = await asyncio.wait_for(queue.get(), timeout=2.0)
            second = await asyncio.wait_for(queue.get(), timeout=2.0)
        finally:
            trace_bus.unsubscribe(session_id, queue)
        return f"published and received 2 events ({first.status} then {second.status})"

    plan: list[tuple[str, str, Callable[[], Awaitable[str]], float]] = [
        ("database", "Metadata DB", database, 5.0),
        ("embed", "Tiny embedding", embed, 60.0),
        ("dense_search", "Dense search", dense_search, 15.0),
        ("keyword_search", "Keyword search", keyword_search, 10.0),
        ("graph", "Graph store", graph, 5.0),
        ("generate", "1-token generation", generate, 90.0),
        ("trace", "Trace bus round trip", trace_round_trip, 5.0),
    ]
    return [await _timed(name, label, fn, timeout) for name, label, fn, timeout in plan]
