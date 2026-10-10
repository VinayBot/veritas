from __future__ import annotations

import pytest

from app.ingestion.scraper import SsrfBlockedError, _check_url_allowed


@pytest.mark.parametrize(
    "url",
    [
        "http://localhost/",
        "http://127.0.0.1/",
        "http://169.254.169.254/latest/meta-data/",  # cloud metadata endpoint
        "http://10.0.0.5/",
        "http://192.168.1.1/",
        "ftp://example.com/",
        "file:///etc/passwd",
    ],
)
def test_blocks_internal_and_disallowed_schemes(url: str) -> None:
    with pytest.raises(SsrfBlockedError):
        _check_url_allowed(url)


def test_allows_public_host() -> None:
    _check_url_allowed("https://example.com/")
