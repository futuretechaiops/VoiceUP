"""Polite, bounded, same-site crawler with an HTTP fetcher and a headless-browser fetcher.

Single-page apps (for example Lovable, React, Next.js client rendering) return an empty shell to
plain HTTP, so ``auto`` mode switches to rendering the page in Chromium when a page has almost
no text. robots.txt is honoured, only allow-listed hosts are visited, query strings and fragments
are ignored, and every redirect hop is re-validated.
"""

import logging
import os
import time
from collections import deque
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Protocol
from urllib.parse import urldefrag, urljoin, urlsplit, urlunsplit
from urllib.robotparser import RobotFileParser

import httpx

from .extract import Extracted, extract
from .netguard import UnsafeUrl, is_public_host, validate_url

log = logging.getLogger("concierge.crawler")
USER_AGENT = "FutureVoiceUPBot/1.0 (+site assistant knowledge crawler)"
SKIP_EXTENSIONS = (
    ".pdf", ".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg", ".ico", ".zip", ".mp4", ".mp3",
    ".css", ".js", ".json", ".xml", ".txt", ".woff", ".woff2", ".ttf", ".docx", ".xlsx", ".pptx",
)  # fmt: skip
MAX_BYTES = 3_000_000
MIN_TEXT_FOR_STATIC = 250


@dataclass
class Fetched:
    url: str  # final URL after redirects
    status: int
    html: str


class Fetcher(Protocol):
    def fetch(self, url: str) -> Fetched | None: ...
    def close(self) -> None: ...


def normalise(url: str, base: str | None = None) -> str | None:
    """Absolute, fragment-free, query-free, lower-case-host URL; None if not crawlable."""
    absolute = urljoin(base, url) if base else url
    absolute, _ = urldefrag(absolute)
    parts = urlsplit(absolute)
    if parts.scheme not in {"http", "https"} or not parts.hostname:
        return None
    path = parts.path or "/"
    if path.lower().endswith(SKIP_EXTENSIONS):
        return None
    if len(path) > 300:
        return None
    netloc = parts.hostname.lower() + (f":{parts.port}" if parts.port else "")
    return urlunsplit((parts.scheme, netloc, path.rstrip("/") or "/", "", ""))


class HttpFetcher:
    def __init__(self, allowed_hosts: set[str], *, allow_private: bool = False) -> None:
        self._allowed = allowed_hosts
        self._allow_private = allow_private
        self._client = httpx.Client(
            headers={"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml"},
            timeout=15.0,
            follow_redirects=False,
        )

    def fetch(self, url: str) -> Fetched | None:
        current = url
        for _ in range(6):
            validate_url(current, self._allowed, allow_private=self._allow_private)
            response = self._client.get(current)
            if response.is_redirect and (location := response.headers.get("location")):
                current = urljoin(current, location)  # re-validated at the top of the loop
                continue
            ctype = response.headers.get("content-type", "")
            if response.status_code >= 400 or "html" not in ctype.lower():
                return Fetched(current, response.status_code, "")
            if len(response.content) > MAX_BYTES:
                return None
            return Fetched(current, response.status_code, response.text)
        return None

    def close(self) -> None:
        self._client.close()


class BrowserFetcher:
    """Renders pages in headless Chromium. Subresources to non-public hosts are blocked.

    Playwright's sync API refuses to run inside a thread that has an asyncio loop, so every
    browser call runs on one dedicated worker thread. Set CHROMIUM_EXECUTABLE_PATH to use a
    system Chromium instead of the one Playwright downloads.
    """

    def __init__(self, allowed_hosts: set[str], *, allow_private: bool = False) -> None:
        self._allowed = allowed_hosts
        self._allow_private = allow_private
        self._host_ok: dict[str, bool] = {}
        self._pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="browser")
        self._pool.submit(self._start).result()

    def _start(self) -> None:
        from playwright.sync_api import sync_playwright

        self._pw = sync_playwright().start()
        exe = os.environ.get("CHROMIUM_EXECUTABLE_PATH") or None
        self._browser = self._pw.chromium.launch(executable_path=exe)
        self._context = self._browser.new_context(user_agent=USER_AGENT)
        self._context.route("**/*", self._route)

    def _route(self, route, request) -> None:  # type: ignore[no-untyped-def]
        host = (urlsplit(request.url).hostname or "").lower()
        blocked = False
        if request.url.startswith(("data:", "blob:")):
            blocked = False
        elif request.is_navigation_request() and host not in self._allowed:
            blocked = True
        elif not self._allow_private:
            if host not in self._host_ok:
                self._host_ok[host] = is_public_host(host)
            blocked = not self._host_ok[host]
        if blocked:
            route.abort()
        else:
            route.continue_()

    def fetch(self, url: str) -> Fetched | None:
        validate_url(url, self._allowed, allow_private=self._allow_private)
        return self._pool.submit(self._fetch, url).result()

    def _fetch(self, url: str) -> Fetched | None:
        page = self._context.new_page()
        try:
            response = page.goto(url, wait_until="networkidle", timeout=30_000)
            page.wait_for_timeout(500)  # let late client-side renders settle
            final = page.url
            validate_url(final, self._allowed, allow_private=self._allow_private)
            return Fetched(final, response.status if response else 0, page.content())
        except UnsafeUrl:
            raise
        except Exception as exc:  # noqa: BLE001 - one bad page must not stop the crawl
            log.warning("browser fetch failed for %s: %s", url, type(exc).__name__)
            return None
        finally:
            page.close()

    def _stop(self) -> None:
        self._context.close()
        self._browser.close()
        self._pw.stop()

    def close(self) -> None:
        try:
            self._pool.submit(self._stop).result()
        finally:
            self._pool.shutdown()


@dataclass
class CrawledPage:
    url: str
    title: str
    extracted: Extracted


class SiteCrawler:
    def __init__(
        self,
        start_url: str,
        *,
        allowed_hosts: set[str] | None = None,
        max_pages: int = 200,
        delay: float = 0.5,
        mode: str = "auto",  # auto | http | browser
        allow_private: bool = False,
    ) -> None:
        start = normalise(start_url)
        if start is None:
            raise UnsafeUrl("Invalid start URL")
        host = urlsplit(start).hostname or ""
        bare = host.removeprefix("www.")
        self.allowed = allowed_hosts or {bare, f"www.{bare}"}
        self.start = start
        self.max_pages = max_pages
        self.delay = delay
        self.mode = mode
        self.allow_private = allow_private
        self._robots: RobotFileParser | None = None
        self.skipped: list[tuple[str, str]] = []

    def _load_robots(self, fetcher: HttpFetcher) -> None:
        parts = urlsplit(self.start)
        robots_url = f"{parts.scheme}://{parts.netloc}/robots.txt"
        parser = RobotFileParser()
        try:
            validate_url(robots_url, self.allowed, allow_private=self.allow_private)
            response = fetcher._client.get(robots_url)  # noqa: SLF001
            if response.status_code >= 500:
                parser.disallow_all = True  # type: ignore[attr-defined]
            elif response.status_code >= 400:
                parser.allow_all = True  # type: ignore[attr-defined]
            else:
                parser.parse(response.text.splitlines())
        except (httpx.HTTPError, UnsafeUrl):
            parser.disallow_all = True  # type: ignore[attr-defined]  # RFC 9309: unreachable robots.txt means do not crawl
        self._robots = parser

    def crawl(self) -> Iterator[CrawledPage]:
        http = HttpFetcher(self.allowed, allow_private=self.allow_private)
        browser: BrowserFetcher | None = None
        use_browser = self.mode == "browser"
        try:
            self._load_robots(http)
            queue: deque[str] = deque([self.start])
            seen: set[str] = {self.start}
            emitted = 0
            while queue and emitted < self.max_pages:
                url = queue.popleft()
                assert self._robots is not None  # noqa: S101
                if not self._robots.can_fetch(USER_AGENT, url):
                    self.skipped.append((url, "robots.txt"))
                    continue
                try:
                    fetched: Fetched | None = None
                    if not use_browser:
                        fetched = http.fetch(url)
                        text_len = (
                            len(extract(fetched.html).text) if fetched and fetched.html else 0
                        )
                        if (
                            self.mode == "auto"
                            and fetched
                            and fetched.status < 400
                            and text_len < MIN_TEXT_FOR_STATIC
                        ):
                            log.info(
                                "little static text at %s; switching to browser rendering", url
                            )
                            use_browser = True
                            fetched = None
                    if use_browser:
                        if browser is None:
                            browser = BrowserFetcher(self.allowed, allow_private=self.allow_private)
                        fetched = browser.fetch(url)
                except UnsafeUrl as exc:
                    self.skipped.append((url, f"unsafe: {exc}"))
                    continue
                except httpx.HTTPError as exc:
                    self.skipped.append((url, f"http error: {type(exc).__name__}"))
                    continue
                if fetched is None or fetched.status >= 400 or not fetched.html:
                    self.skipped.append((url, f"status {fetched.status if fetched else 'none'}"))
                    continue
                final = normalise(fetched.url) or url
                page = extract(fetched.html)
                emitted += 1
                yield CrawledPage(url=final, title=page.title or final, extracted=page)
                for href in page.links:
                    link = normalise(href, fetched.url)
                    if (
                        link
                        and link not in seen
                        and (urlsplit(link).hostname or "") in self.allowed
                    ):
                        seen.add(link)
                        queue.append(link)
                time.sleep(self.delay)
        finally:
            http.close()
            if browser is not None:
                browser.close()
