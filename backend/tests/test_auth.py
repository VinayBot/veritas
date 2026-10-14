"""API keys and roles (app/core/auth.py): off by default; when on, every route is covered by the
policy table, missing or wrong keys get 401, and a role below the route's requirement gets 403."""

from __future__ import annotations

import pytest

from app.core.auth import POLICY, PUBLIC, required_role
from app.core.config import get_settings
from app.main import app

KEYS = "view-key-1111:viewer,analyst-key-2222:analyst,admin-key-3333:admin"


@pytest.fixture
def auth_on(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "auth_enabled", True)
    monkeypatch.setattr(settings, "api_keys", KEYS)


def _h(key: str) -> dict[str, str]:
    return {"X-API-Key": key}


async def test_off_by_default_everything_is_reachable(client) -> None:
    assert get_settings().auth_enabled is False
    assert (await client.get("/api/v1/audit")).status_code == 200


async def test_without_a_key_only_the_liveness_probe_answers(client, auth_on) -> None:
    assert (await client.get("/api/v1/health")).status_code == 200
    resp = await client.get("/api/v1/documents")
    assert resp.status_code == 401
    assert resp.headers["WWW-Authenticate"] == "Bearer"
    assert (await client.get("/api/v1/documents", headers=_h("wrong-key"))).status_code == 401


async def test_roles_are_ordered(client, auth_on) -> None:
    # Reading: every role.
    for key in ("view-key-1111", "analyst-key-2222", "admin-key-3333"):
        assert (await client.get("/api/v1/documents", headers=_h(key))).status_code == 200
    # The audit log: admin only.
    assert (await client.get("/api/v1/audit", headers=_h("analyst-key-2222"))).status_code == 403
    assert (await client.get("/api/v1/audit", headers=_h("admin-key-3333"))).status_code == 200
    # Starting work (a measurement): analyst and up. The handler then 404s on the fake id.
    url = "/api/v1/documents/missing/measure"
    assert (await client.post(url, headers=_h("view-key-1111"))).status_code == 403
    assert (await client.post(url, headers=_h("analyst-key-2222"))).status_code == 404
    # Deleting: admin only.
    url = "/api/v1/documents/missing"
    assert (await client.delete(url, headers=_h("analyst-key-2222"))).status_code == 403
    assert (await client.delete(url, headers=_h("admin-key-3333"))).status_code == 404


async def test_bearer_tokens_are_accepted(client, auth_on) -> None:
    resp = await client.get("/api/v1/documents", headers={"Authorization": "Bearer view-key-1111"})
    assert resp.status_code == 200


def test_every_route_is_covered_and_only_reads_and_questions_are_open_to_viewers() -> None:
    viewer_writes = set()
    for path, operations in app.openapi()["paths"].items():
        for method in operations:
            role = required_role(method.upper(), path)
            assert role in ("viewer", "analyst", "admin", PUBLIC), (method, path)
            if method != "get" and role in ("viewer", PUBLIC):
                viewer_writes.add(f"{method.upper()} {path}")
    assert viewer_writes == {
        "POST /api/v1/chat",
        "POST /api/v1/retrieval/search",
        "POST /api/v1/rag/compare/estimate",
        "POST /api/v1/runs/{run_id}/cancel",
    }
    assert required_role("GET", "/ws/trace/{session_id}") == "viewer"
    assert POLICY  # the table is the single source of truth


def test_sensitive_routes_need_admin() -> None:
    for method, path in [
        ("POST", "/api/v1/pii/reveal"),
        ("PUT", "/api/v1/models/selection"),
        ("POST", "/api/v1/redteam/run"),
        ("DELETE", "/api/v1/documents/{document_id}"),
        ("GET", "/api/v1/audit"),
    ]:
        assert required_role(method, path) == "admin", (method, path)
