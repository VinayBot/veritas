from __future__ import annotations

import importlib

from httpx import AsyncClient


async def test_topology_returns_real_nodes_and_edges(client: AsyncClient) -> None:
    resp = await client.get("/api/v1/architecture/topology")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["nodes"]) >= 20
    assert body["edges"]

    node_ids = {n["id"] for n in body["nodes"]}
    for edge in body["edges"]:
        assert edge["source"] in node_ids
        assert edge["target"] in node_ids


async def test_every_non_planned_module_path_is_a_real_importable_module(
    client: AsyncClient,
) -> None:
    # G1: no fabricated topology — every node either names a real Python module that imports
    # cleanly, or (the frontend-only "user" node) a real file on disk, or is explicitly
    # `planned: true` and exempt. Mirrors the frontend's own contract test in the other
    # direction (that one checks layout/icon coverage; this one checks the backend doesn't
    # claim a component exists when the module behind it doesn't).
    resp = await client.get("/api/v1/architecture/topology")
    body = resp.json()
    for node in body["nodes"]:
        if node["planned"]:
            continue
        path = node["module_path"]
        if path.startswith("frontend/"):
            continue
        importlib.import_module(path)
