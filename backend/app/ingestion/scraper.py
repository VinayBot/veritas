"""URL ingestion: fetch a public page into clean Markdown, exactly like an uploaded document.

SSRF guard blocks localhost/private/link-local/reserved addresses, re-checked on every redirect
hop (not just the original URL) since a redirect is the classic SSRF bypass. robots.txt is
respected. Size and time are capped. An optional same-domain crawl follows links up to a depth
and page-count limit. Playwright is used only as a fallback when the static HTML looks like an
empty JS app shell.
"""

from __future__ import annotations

import ipaddress
import socket
import time
from dataclasses import dataclass, field
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser

import httpx
import trafilatura

from app.core.config import get_settings

USER_AGENT = "VeritasBot/0.1 (+local RAG ingestion; respects robots.txt)"


class SsrfBlockedError(Exception):
    pass


class RobotsDisallowedError(Exception):
    pass


@dataclass
class ScrapedPage:
    url: str
    text: str
    fetch_time: float
    title: str | None = None


@dataclass
class ScrapeResult:
    pages: list[ScrapedPage] = field(default_factory=list)


def _check_host_not_internal(hostname: str) -> None:
    try:
        infos = socket.getaddrinfo(hostname, None)
    except socket.gaierror as exc:
        raise SsrfBlockedError(f"Could not resolve host: {hostname}") from exc
    for *_rest, sockaddr in infos:
        ip = ipaddress.ip_address(sockaddr[0])
        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_reserved
            or ip.is_multicast
            or ip.is_unspecified
        ):
            raise SsrfBlockedError(f"Blocked internal/private address for {hostname}: {ip}")


def _check_url_allowed(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise SsrfBlockedError(f"Scheme not allowed: {parsed.scheme!r}")
    if not parsed.hostname:
        raise SsrfBlockedError("URL has no host")
    _check_host_not_internal(parsed.hostname)


def _robots_allows(url: str, timeout: float) -> bool:
    parsed = urlparse(url)
    robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
    try:
        _check_url_allowed(robots_url)
        resp = httpx.get(robots_url, timeout=timeout, headers={"User-Agent": USER_AGENT})
        if resp.status_code >= 400:
            return True
        parser = RobotFileParser()
        parser.parse(resp.text.splitlines())
        return parser.can_fetch(USER_AGENT, url)
    except (httpx.HTTPError, SsrfBlockedError):
        return True


def _fetch_raw_html(url: str, timeout: float, max_bytes: int) -> str:
    current = url
    for _ in range(5):
        _check_url_allowed(current)
        with httpx.Client(follow_redirects=False, timeout=timeout) as client:
            with client.stream("GET", current, headers={"User-Agent": USER_AGENT}) as resp:
                if resp.status_code in (301, 302, 303, 307, 308) and "location" in resp.headers:
                    current = urljoin(current, resp.headers["location"])
                    continue
                resp.raise_for_status()
                chunks: list[bytes] = []
                total = 0
                for chunk in resp.iter_bytes():
                    total += len(chunk)
                    if total > max_bytes:
                        raise ValueError(f"Response exceeded {max_bytes} byte cap")
                    chunks.append(chunk)
                encoding = resp.encoding or "utf-8"
                return b"".join(chunks).decode(encoding, errors="replace")
    raise SsrfBlockedError("Too many redirects")


def _looks_like_js_shell(html: str, extracted_text: str | None) -> bool:
    return len(html) > 2000 and len(extracted_text or "") < 200


def _render_with_playwright(url: str, timeout: float) -> str:
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        try:
            page = browser.new_page(user_agent=USER_AGENT)
            page.goto(url, timeout=timeout * 1000, wait_until="networkidle")
            html = page.content()
        finally:
            browser.close()
    return html


def _extract(html: str, url: str) -> tuple[str, str | None]:
    extracted = trafilatura.extract(html, url=url, output_format="markdown", with_metadata=False)
    metadata = trafilatura.extract_metadata(html)
    title = metadata.title if metadata else None
    return extracted or "", title


def _same_domain_links(html: str, base_url: str) -> list[str]:
    import re

    base_host = urlparse(base_url).netloc
    links = set()
    for match in re.finditer(r'href=["\']([^"\'#]+)', html):
        href = urljoin(base_url, match.group(1))
        parsed = urlparse(href)
        if parsed.scheme in ("http", "https") and parsed.netloc == base_host:
            links.add(href.split("#")[0])
    return sorted(links)


def scrape_url(
    url: str,
    crawl_depth: int = 0,
    max_pages: int | None = None,
) -> ScrapeResult:
    """Synchronous — called from a thread by the async service layer (httpx.Client + sync
    Playwright are both blocking APIs; see app/ingestion/service.py)."""
    settings = get_settings()
    timeout = float(settings.scrape_timeout_seconds)
    max_bytes = settings.scrape_max_bytes
    max_depth = min(crawl_depth, settings.scrape_max_crawl_depth)
    page_limit = min(max_pages or settings.scrape_max_pages, settings.scrape_max_pages)

    _check_url_allowed(url)
    if not _robots_allows(url, timeout):
        raise RobotsDisallowedError(f"robots.txt disallows fetching {url}")

    visited: set[str] = set()
    queue: list[tuple[str, int]] = [(url, 0)]
    pages: list[ScrapedPage] = []

    while queue and len(pages) < page_limit:
        current_url, depth = queue.pop(0)
        if current_url in visited:
            continue
        visited.add(current_url)

        try:
            _check_url_allowed(current_url)
            if current_url != url and not _robots_allows(current_url, timeout):
                continue
            html = _fetch_raw_html(current_url, timeout, max_bytes)
        except (SsrfBlockedError, httpx.HTTPError, ValueError):
            continue

        text, title = _extract(html, current_url)
        if _looks_like_js_shell(html, text):
            try:
                html = _render_with_playwright(current_url, timeout)
                text, title = _extract(html, current_url)
            except Exception:
                pass  # Playwright not installed / failed to launch — keep the static extraction.

        pages.append(ScrapedPage(url=current_url, text=text, fetch_time=time.time(), title=title))

        if depth < max_depth and len(pages) < page_limit:
            for link in _same_domain_links(html, current_url):
                if link not in visited:
                    queue.append((link, depth + 1))

    return ScrapeResult(pages=pages)
