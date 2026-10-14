"""API keys and roles, enforced on every route from one policy table.

Off by default (AUTH_ENABLED=false): Veritas is a local, single-user tool, and the UI must
open with no setup. Turned on, every request needs an API key, sent as `X-API-Key` (or
`Authorization: Bearer <key>`; `?api_key=` for the trace WebSocket, which browsers cannot send
headers to). Each key carries a role, and each role includes the ones below it:

- viewer:  read everything except the audit log, ask questions, search
- analyst: also upload, compare, measure, run evaluations, change a document's strategy
- admin:   also delete, reveal PII, change models and defaults, run the red-team suite,
           read the audit log

The policy is a table matched top to bottom (method, route template) rather than a decorator
on each endpoint, so the whole access model reads in one place and a new endpoint cannot be
left open by forgetting one: an unmatched write requires analyst.
"""

from __future__ import annotations

import hmac
import re
from dataclasses import dataclass

from fastapi import HTTPException, status
from starlette.requests import HTTPConnection

from app.core.config import get_settings

ROLES = ("viewer", "analyst", "admin")
_RANK = {role: i for i, role in enumerate(ROLES)}
PUBLIC = "public"

# (methods, route template regex, required role). First match wins.
POLICY: tuple[tuple[frozenset[str], re.Pattern[str], str], ...] = tuple(
    (frozenset(methods.split()), re.compile(pattern), role)
    for methods, pattern, role in (
        ("GET", r"^/api/v1/health$", PUBLIC),
        ("DELETE", r".*", "admin"),
        ("POST", r"^/api/v1/pii/reveal$", "admin"),
        ("PUT POST", r"^/api/v1/models/", "admin"),
        ("PUT", r"^/api/v1/rag/default$", "admin"),
        ("POST", r"^/api/v1/redteam/", "admin"),
        ("GET", r"^/api/v1/audit", "admin"),
        ("POST", r"^/api/v1/chat$", "viewer"),
        ("POST", r"^/api/v1/retrieval/search$", "viewer"),
        ("POST", r"^/api/v1/rag/compare/estimate$", "viewer"),
        ("POST", r"^/api/v1/runs/\{run_id\}/cancel$", "viewer"),
        ("GET HEAD", r".*", "viewer"),
        ("POST PUT PATCH", r".*", "analyst"),
    )
)


@dataclass(frozen=True)
class Principal:
    role: str
    key_id: str  # the key's last four characters, for logs; never the key itself


def _keys() -> dict[str, str]:
    """API_KEYS: comma-separated `key:role` pairs."""
    keys: dict[str, str] = {}
    for entry in get_settings().api_keys.split(","):
        key, _, role = entry.strip().rpartition(":")
        if key and role in ROLES:
            keys[key] = role
    return keys


def required_role(method: str, route: str) -> str:
    for methods, pattern, role in POLICY:
        if method in methods and pattern.search(route):
            return role
    return "analyst"


def _presented_key(conn: HTTPConnection) -> str | None:
    key = conn.headers.get("x-api-key")
    if not key:
        auth = conn.headers.get("authorization", "")
        if auth.lower().startswith("bearer "):
            key = auth[7:].strip()
    return key or conn.query_params.get("api_key")


def _lookup(presented: str) -> str | None:
    # Constant-time comparison against every key, so timing does not reveal a near match.
    found = None
    for key, role in _keys().items():
        if hmac.compare_digest(presented.encode(), key.encode()):
            found = role
    return found


def _route_template(conn: HTTPConnection) -> str:
    """The matched route's template ("/api/v1/documents/{document_id}"), so a rule never
    depends on ids in the URL. Included routers report it without their prefix; the prefix is
    restored from the request path."""
    template = getattr(conn.scope.get("route"), "path", None) or conn.url.path
    for prefix in ("/api/v1",):
        if conn.url.path.startswith(prefix + "/") and not template.startswith(prefix + "/"):
            template = prefix + template
    return template


async def authorize(conn: HTTPConnection) -> Principal:
    """The dependency every router carries. Raises 401 without a valid key and 403 when the
    key's role is below what the route requires."""
    if not get_settings().auth_enabled:
        return Principal(role="admin", key_id="local")
    route = _route_template(conn)
    method = "GET" if conn.scope["type"] == "websocket" else conn.scope.get("method", "GET")
    needed = required_role(method, route)
    if needed == PUBLIC:
        return Principal(role="viewer", key_id="public")
    presented = _presented_key(conn)
    role = _lookup(presented) if presented else None
    if role is None:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "A valid API key is required (X-API-Key header).",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if _RANK[role] < _RANK[needed]:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, f"This needs the {needed} role; the key has {role}."
        )
    return Principal(role=role, key_id=presented[-4:] if presented else "")
