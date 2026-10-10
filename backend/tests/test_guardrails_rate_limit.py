from __future__ import annotations

import pytest

from app.core.config import get_settings
from app.guardrails import rate_limit


@pytest.fixture(autouse=True)
def _clear():
    rate_limit.clear()
    yield
    rate_limit.clear()


def test_allows_requests_under_the_limit() -> None:
    session_id = "s1"
    limit = get_settings().rate_limit_per_minute
    for _ in range(limit):
        assert rate_limit.check(session_id) is True


def test_blocks_requests_over_the_limit() -> None:
    session_id = "s2"
    limit = get_settings().rate_limit_per_minute
    for _ in range(limit):
        rate_limit.check(session_id)
    assert rate_limit.check(session_id) is False


def test_sessions_are_independent() -> None:
    limit = get_settings().rate_limit_per_minute
    for _ in range(limit):
        rate_limit.check("session-a")
    assert rate_limit.check("session-a") is False
    assert rate_limit.check("session-b") is True
