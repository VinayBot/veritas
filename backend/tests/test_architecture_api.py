from __future__ import annotations

import importlib
import uuid

import pytest
from httpx import AsyncClient

from app.core import topology
from app.core.health import ProbeResult
from app.core.tracing import trace_bus

VALID_STATUSES = {"healthy", "degraded", "down", "disabled", "not_configured"}
VALID_KINDS = {"request", "data", "trace", "optional"}


async def _graph(client: AsyncClient) -> dict:
    resp = await client.get("/api/v1/architecture/graph")
    assert resp.status_code == 200, resp.text
    return resp.json()


async def test_graph_describes_the_real_modules(client: AsyncClient) -> None:
    body = await _graph(client)
    ids = {n["id"] for n in body["nodes"]}
    # Every package under app/ is on the diagram — discovered, not listed by hand here.
    for package in topology.discovered_packages():
        assert any(i == package or i.startswith(package + ".") for i in ids), package
    assert {"client", "api", "ingestion", "privacy", "retrieval", "guardrails", "llm"} <= ids
    for node in body["nodes"]:
        assert node["status"] in VALID_STATUSES
        assert node["one_line_purpose"]
        assert node["probe_kind"]
    assert [s["id"] for s in body["stages"]] == [1, 2, 3, 4, 5]


async def test_every_node_names_a_real_importable_module(client: AsyncClient) -> None:
    for node in (await _graph(client))["nodes"]:
        path = node["module_path"]
        if path.startswith("frontend"):
            continue
        importlib.import_module(path)


async def test_edges_connect_existing_nodes_with_known_kinds(client: AsyncClient) -> None:
    body = await _graph(client)
    ids = {n["id"] for n in body["nodes"]}
    assert body["edges"]
    for edge in body["edges"]:
        assert edge["source"] in ids and edge["target"] in ids, edge
        assert edge["kind"] in VALID_KINDS
        assert edge["derived"] in {"langgraph", "declared"}
    assert len({e["id"] for e in body["edges"]}) == len(body["edges"])


async def test_agent_nodes_and_edges_come_from_the_compiled_langgraph(
    client: AsyncClient,
) -> None:
    from app.agents.graph import get_agent_graph

    compiled = get_agent_graph().get_graph()
    real_nodes = {n for n in compiled.nodes if not n.startswith("__")}
    real_edges = {
        (e.source, e.target)
        for e in compiled.edges
        if not e.source.startswith("__") and not e.target.startswith("__")
    }

    body = await _graph(client)
    shown_nodes = {
        n["id"].removeprefix("agents.")
        for n in body["nodes"]
        if n["parent"] == "agents" and n["id"] != "agents.orchestrator"
    }
    shown_edges = {
        (e["source"].removeprefix("agents."), e["target"].removeprefix("agents."))
        for e in body["edges"]
        if e["derived"] == "langgraph" and e["target"] != "api"
    }
    assert shown_nodes == real_nodes
    assert shown_edges == real_edges
    # Conditional edges in the graph are marked optional on the diagram.
    conditional = {(e.source, e.target) for e in compiled.edges if e.conditional}
    for edge in body["edges"]:
        key = (edge["source"].removeprefix("agents."), edge["target"].removeprefix("agents."))
        if edge["derived"] == "langgraph" and key in conditional:
            assert edge["kind"] == "optional"


def test_every_declared_edge_is_backed_by_real_imports() -> None:
    """A declared edge is only allowed if the call chain it names exists in code: each
    consecutive pair in [source, *via, target] must be linked by an import."""
    module_of = {spec.id: spec.module_path for spec in topology.MANIFEST}
    module_of["agents.orchestrator"] = "app.agents.orchestrator"
    for name in topology.AGENT_NODE_PURPOSE:
        module_of.setdefault(f"agents.{name}", "app.agents")
    module_of[topology.AGENTS_ENTRY] = "app.agents.graph"

    unbacked = []
    for edge in topology.DECLARED_EDGES:
        chain = [module_of[edge.source], *edge.via, module_of[edge.target]]
        if any(link.startswith("frontend") for link in chain):
            continue
        if not all(topology.module_exists(link) for link in chain):
            continue  # an endpoint that is not present yet produces no edge at all
        for a, b in zip(chain, chain[1:], strict=False):
            if a == b or a.startswith(b + ".") or b.startswith(a + "."):
                continue
            if not topology.imports_between(a, b):
                unbacked.append(f"{edge.source} -> {edge.target}: no import between {a} and {b}")
    assert unbacked == []


def test_a_module_that_no_longer_exists_disappears_from_the_graph(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The acceptance test for "code-derived": remove a module and its node and edges go,
    with no other change. Simulated by making one package undiscoverable."""
    real_exists = topology.module_exists
    real_discovered = topology.discovered_packages
    before = topology.build_topology([])
    assert any(n["id"] == "council" for n in before.nodes)
    assert any("council" in (e["source"], e["target"]) for e in before.edges)

    monkeypatch.setattr(
        topology, "module_exists", lambda path: path != "app.council" and real_exists(path)
    )
    monkeypatch.setattr(
        topology, "discovered_packages", lambda: [p for p in real_discovered() if p != "council"]
    )
    after = topology.build_topology([])
    assert not any(n["id"] == "council" for n in after.nodes)
    assert not any("council" in (e["source"], e["target"]) for e in after.edges)
    assert len(after.nodes) == len(before.nodes) - 1


def test_a_new_undescribed_package_appears_on_the_graph(monkeypatch: pytest.MonkeyPatch) -> None:
    real_discovered = topology.discovered_packages
    monkeypatch.setattr(topology, "discovered_packages", lambda: [*real_discovered(), "llm_extras"])
    built = topology.build_topology([])
    node = next(n for n in built.nodes if n["id"] == "llm_extras")
    assert node["documented"] is False
    assert node["stage"] is None


def test_disabled_by_config_is_distinct_from_broken() -> None:
    down = ProbeResult("ollama", "Ollama", "down", "unreachable", "dependency", error="refused")
    built = topology.build_topology([down])
    by_id = {n["id"]: n for n in built.nodes}
    assert by_id["llm"]["status"] == "down"
    assert "refused" in by_id["llm"]["status_detail"]
    # The Neo4j adapter is simply not in use — never reported as an outage.
    assert by_id["stores.graph.neo4j"]["status"] == "not_configured"
    assert by_id["stores.graph.neo4j"]["probe_kind"] == "config"
    # A module with nothing to probe says so instead of claiming a verified "healthy".
    assert by_id["chunking"]["probe_kind"] == "import"


async def test_node_counts_and_latency_come_from_real_trace_events(client: AsyncClient) -> None:
    session_id = f"arch-{uuid.uuid4()}"
    before = next(n for n in (await _graph(client))["nodes"] if n["id"] == "chunking")

    async with trace_bus.stage(session_id, "chunk") as handle:
        handle.set_output("3 chunks")

    after = next(n for n in (await _graph(client))["nodes"] if n["id"] == "chunking")
    assert after["invocation_count"] == before["invocation_count"] + 1
    assert after["last_latency_ms"] is not None
    assert after["p50_latency_ms"] is not None

    events = await client.get("/api/v1/architecture/nodes/chunking/events")
    assert events.status_code == 200
    latest = events.json()["events"][0]
    assert latest["session_id"] == session_id
    assert latest["status"] == "done"
    assert latest["output_preview"] == "3 chunks"
    assert len(events.json()["events"]) <= 10


async def test_stage_to_node_places_trace_stages_on_the_diagram(client: AsyncClient) -> None:
    body = await _graph(client)
    ids = {n["id"] for n in body["nodes"]}
    mapping = body["stage_to_node"]
    assert mapping["parse"] == "ingestion"
    assert mapping["pii_vault"] == "privacy"
    assert mapping["planner"] == "agents.planner"
    assert set(mapping.values()) <= ids


async def test_unknown_node_events_404(client: AsyncClient) -> None:
    resp = await client.get("/api/v1/architecture/nodes/nope/events")
    assert resp.status_code == 404
    assert resp.json()["code"] == "node_not_found"
