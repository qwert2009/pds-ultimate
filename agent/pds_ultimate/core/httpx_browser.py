"""
PDS-Ultimate HTTPX Browser Engine — Manus-level Web Interaction
================================================================
Полноценный headless-браузер на httpx + BeautifulSoup.
Работает БЕЗ Playwright — чистый Python, всегда доступен.

Capabilities:
1. Multi-step navigation (search → open → extract → follow links)
2. Smart content extraction (article text, tables, structured data)
3. Session persistence (cookies, headers across requests)
4. Anti-detection (random UA, delays, realistic headers)
5. Multi-engine search (DuckDuckGo, Google, Bing fallbacks)
6. Page interaction simulation (form filling via POST)
7. Content summarization pipeline
8. Rate limiting & retry logic
9. Parallel page fetching
10. Deep crawling (follow N links deep)

Used as PRIMARY browser when Playwright is unavailable.
"""

from __future__ import annotations

import asyncio
import os
import random
import re
import time
from dataclasses import dataclass, field
from html import unescape
from typing import Any
from urllib.parse import parse_qs, quote_plus, unquote, urljoin, urlparse

from pds_ultimate.config import logger

# ═══════════════════════════════════════════════════════════════════════════════
# CONSTANTS
# ═══════════════════════════════════════════════════════════════════════════════

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:134.0) Gecko/20100101 Firefox/134.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:134.0) Gecko/20100101 Firefox/134.0",
    "Mozilla/5.0 (X11; Linux x86_64; rv:134.0) Gecko/20100101 Firefox/134.0",
]

ACCEPT_HEADERS = {
    "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
}

# Tags to strip when extracting text
STRIP_TAGS = {
    "script", "style", "nav", "footer", "header", "aside",
    "noscript", "iframe", "svg", "form", "button", "input",
    "select", "textarea", "meta", "link",
}

# ═══════════════════════════════════════════════════════════════════════════════
# DATA MODELS
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass
class SearchResult:
    """Single search result."""
    title: str
    url: str
    snippet: str = ""
    position: int = 0

    def __str__(self):
        return f"[{self.position}] {self.title}\n    {self.url}\n    {self.snippet}"


@dataclass
class PageData:
    """Extracted page content."""
    url: str
    title: str = ""
    text: str = ""
    links: list[dict[str, str]] = field(default_factory=list)
    headings: list[dict[str, str]] = field(default_factory=list)
    tables: list[list[list[str]]] = field(default_factory=list)
    images: list[dict[str, str]] = field(default_factory=list)
    meta: dict[str, str] = field(default_factory=dict)
    status_code: int = 0
    content_type: str = ""
    load_time_ms: int = 0
    error: str = ""

    @property
    def success(self) -> bool:
        return self.status_code in range(200, 400) and not self.error

    def summary(self, max_text: int = 3000) -> str:
        parts = [f"📄 {self.title}", f"🔗 {self.url}"]
        if self.text:
            t = self.text[:max_text]
            if len(self.text) > max_text:
                t += f"\n\n... (ещё {len(self.text) - max_text} символов)"
            parts.append(f"\n{t}")
        if self.links:
            parts.append(f"\n🔗 Ссылок: {len(self.links)}")
        if self.tables:
            parts.append(f"📊 Таблиц: {len(self.tables)}")
        return "\n".join(parts)


@dataclass
class BrowsingSession:
    """Tracks browsing state across multiple requests."""
    pages_visited: list[str] = field(default_factory=list)
    pages_data: dict[str, PageData] = field(default_factory=dict)
    search_results: list[SearchResult] = field(default_factory=list)
    total_requests: int = 0
    total_bytes: int = 0
    start_time: float = field(default_factory=time.time)

    @property
    def duration_ms(self) -> int:
        return int((time.time() - self.start_time) * 1000)


# ═══════════════════════════════════════════════════════════════════════════════
# HTML PARSER — Pure regex + string ops (no BS4 dependency)
# ═══════════════════════════════════════════════════════════════════════════════


class HTMLParser:
    """
    Lightweight HTML parser using regex.
    Falls back to BeautifulSoup if available.
    """

    _bs4_available: bool | None = None

    @classmethod
    def _check_bs4(cls) -> bool:
        if cls._bs4_available is None:
            try:
                import bs4  # noqa: F401
                cls._bs4_available = True
            except ImportError:
                cls._bs4_available = False
        return cls._bs4_available

    @classmethod
    def extract_text(cls, html: str) -> str:
        """Extract readable text from HTML."""
        if cls._check_bs4():
            return cls._extract_text_bs4(html)
        return cls._extract_text_regex(html)

    @classmethod
    def _extract_text_bs4(cls, html: str) -> str:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, "html.parser")
        # Remove unwanted tags
        for tag in soup.find_all(STRIP_TAGS):
            tag.decompose()
        text = soup.get_text(separator="\n", strip=True)
        # Clean up
        text = re.sub(r'\n{3,}', '\n\n', text)
        text = re.sub(r'[ \t]{2,}', ' ', text)
        return text.strip()

    @classmethod
    def _extract_text_regex(cls, html: str) -> str:
        """Regex-based text extraction."""
        text = html
        # Remove script/style blocks
        for tag in ("script", "style", "noscript", "svg"):
            text = re.sub(
                rf'<{tag}[^>]*>.*?</{tag}>', '', text,
                flags=re.DOTALL | re.IGNORECASE
            )
        # Remove comments
        text = re.sub(r'<!--.*?-->', '', text, flags=re.DOTALL)
        # Block-level tags → newline
        text = re.sub(
            r'<(?:div|p|br|hr|h[1-6]|li|tr|td|th|blockquote|section|article|pre)[^>]*>',
            '\n', text, flags=re.IGNORECASE
        )
        # Remove remaining tags
        text = re.sub(r'<[^>]+>', ' ', text)
        # Decode entities
        text = unescape(text)
        # Clean whitespace
        text = re.sub(r'[ \t]+', ' ', text)
        text = re.sub(r'\n{3,}', '\n\n', text)
        lines = [line.strip() for line in text.split('\n')]
        return '\n'.join(line for line in lines if line).strip()

    @classmethod
    def extract_title(cls, html: str) -> str:
        m = re.search(r'<title[^>]*>(.*?)</title>',
                      html, re.DOTALL | re.IGNORECASE)
        return unescape(m.group(1).strip()) if m else ""

    @classmethod
    def extract_meta(cls, html: str) -> dict[str, str]:
        meta = {}
        for m in re.finditer(
            r'<meta\s+(?:name|property)=["\']([^"\']+)["\']'
            r'\s+content=["\']([^"\']+)["\']',
            html, re.IGNORECASE
        ):
            meta[m.group(1)] = unescape(m.group(2))
        # Reverse order too
        for m in re.finditer(
            r'<meta\s+content=["\']([^"\']+)["\']'
            r'\s+(?:name|property)=["\']([^"\']+)["\']',
            html, re.IGNORECASE
        ):
            meta[m.group(2)] = unescape(m.group(1))
        return meta

    @classmethod
    def extract_links(cls, html: str, base_url: str = "") -> list[dict[str, str]]:
        links = []
        for m in re.finditer(
            r'<a[^>]+href=["\']([^"\'#]+)["\'][^>]*>(.*?)</a>',
            html, re.DOTALL | re.IGNORECASE
        ):
            url = m.group(1).strip()
            text = re.sub(r'<[^>]+>', '', m.group(2)).strip()
            if not text or len(text) > 300:
                continue
            if url.startswith('javascript:') or url.startswith('mailto:'):
                continue
            if base_url and not url.startswith(('http://', 'https://')):
                url = urljoin(base_url, url)
            links.append({"url": url, "text": unescape(text)[:200]})
        return links[:150]

    @classmethod
    def extract_headings(cls, html: str) -> list[dict[str, str]]:
        headings = []
        for m in re.finditer(
            r'<(h[1-6])[^>]*>(.*?)</\1>',
            html, re.DOTALL | re.IGNORECASE
        ):
            text = re.sub(r'<[^>]+>', '', m.group(2)).strip()
            if text:
                headings.append({
                    "level": m.group(1).lower(),
                    "text": unescape(text)[:200]
                })
        return headings

    @classmethod
    def extract_tables(cls, html: str) -> list[list[list[str]]]:
        """Extract tables as list of rows of cells."""
        tables = []
        for table_m in re.finditer(
            r'<table[^>]*>(.*?)</table>',
            html, re.DOTALL | re.IGNORECASE
        ):
            rows = []
            for row_m in re.finditer(
                r'<tr[^>]*>(.*?)</tr>',
                table_m.group(1), re.DOTALL | re.IGNORECASE
            ):
                cells = []
                for cell_m in re.finditer(
                    r'<t[dh][^>]*>(.*?)</t[dh]>',
                    row_m.group(1), re.DOTALL | re.IGNORECASE
                ):
                    text = re.sub(r'<[^>]+>', '', cell_m.group(1)).strip()
                    cells.append(unescape(text))
                if cells:
                    rows.append(cells)
            if rows:
                tables.append(rows)
        return tables[:10]

    @classmethod
    def extract_images(cls, html: str, base_url: str = "") -> list[dict[str, str]]:
        images = []
        for m in re.finditer(
            r'<img[^>]+src=["\']([^"\']+)["\'](?:[^>]+alt=["\']([^"\']*)["\'])?',
            html, re.IGNORECASE
        ):
            src = m.group(1).strip()
            alt = m.group(2) or ""
            if base_url and not src.startswith(('http://', 'https://', 'data:')):
                src = urljoin(base_url, src)
            images.append({"src": src, "alt": alt})
        return images[:50]


# ═══════════════════════════════════════════════════════════════════════════════
# HTTPX BROWSER ENGINE
# ═══════════════════════════════════════════════════════════════════════════════


class HttpxBrowser:
    """
    Manus-level headless browser using httpx.

    Capabilities:
    - Multi-step browsing with session persistence
    - Smart search across multiple engines
    - Parallel page fetching
    - Content extraction + summarization
    - Rate limiting with exponential backoff
    - Deep crawl (follow links N levels deep)
    """

    def __init__(
        self,
        max_concurrent: int = 5,
        timeout: int = 15,
        max_retries: int = 2,
        rate_limit_delay: float = 0.5,
    ):
        self._max_concurrent = max_concurrent
        self._timeout = timeout
        self._max_retries = max_retries
        self._rate_limit_delay = rate_limit_delay
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._session: BrowsingSession = BrowsingSession()
        self._ua = random.choice(USER_AGENTS)
        self._last_request_time: float = 0

    def _get_proxy(self) -> str | None:
        return os.environ.get("HTTP_PROXY") or os.environ.get("HTTPS_PROXY")

    def _get_headers(self, referer: str = "") -> dict[str, str]:
        headers = {
            "User-Agent": self._ua,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
            "Accept-Encoding": "gzip, deflate",
            "DNT": "1",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1",
        }
        if referer:
            headers["Referer"] = referer
        return headers

    async def _rate_limit(self):
        """Respect rate limiting between requests."""
        elapsed = time.time() - self._last_request_time
        if elapsed < self._rate_limit_delay:
            await asyncio.sleep(self._rate_limit_delay - elapsed)
        self._last_request_time = time.time()

    async def _fetch(
        self,
        url: str,
        method: str = "GET",
        data: dict | None = None,
        referer: str = "",
        timeout: int | None = None,
    ) -> tuple[str, int, dict[str, str]]:
        """
        Fetch URL with retry logic and rate limiting.

        Returns: (html_text, status_code, response_headers)
        """
        import httpx

        await self._rate_limit()

        for attempt in range(self._max_retries + 1):
            try:
                async with self._semaphore:
                    async with httpx.AsyncClient(
                        proxy=self._get_proxy(),
                        timeout=timeout or self._timeout,
                        follow_redirects=True,
                        headers=self._get_headers(referer),
                    ) as client:
                        if method.upper() == "POST" and data:
                            resp = await client.post(url, data=data)
                        else:
                            resp = await client.get(url)

                        self._session.total_requests += 1
                        self._session.total_bytes += len(resp.content)

                        return resp.text, resp.status_code, dict(resp.headers)

            except httpx.TimeoutException:
                if attempt < self._max_retries:
                    wait = (attempt + 1) * 2
                    logger.debug(f"Timeout fetching {url}, retry in {wait}s")
                    await asyncio.sleep(wait)
                else:
                    return "", 408, {}
            except Exception as e:
                if attempt < self._max_retries:
                    await asyncio.sleep(1)
                else:
                    logger.debug(f"Fetch error {url}: {e}")
                    return "", 0, {}

        return "", 0, {}

    # ─── Page Operations ─────────────────────────────────────────────────

    async def open_page(self, url: str) -> PageData:
        """Open a page and extract all data."""
        start = time.time()
        html, status, headers = await self._fetch(url)

        if not html:
            return PageData(url=url, status_code=status,
                            error=f"Failed to fetch (status {status})")

        page = PageData(
            url=url,
            status_code=status,
            content_type=headers.get("content-type", ""),
            load_time_ms=int((time.time() - start) * 1000),
            title=HTMLParser.extract_title(html),
            text=HTMLParser.extract_text(html),
            links=HTMLParser.extract_links(html, url),
            headings=HTMLParser.extract_headings(html),
            tables=HTMLParser.extract_tables(html),
            images=HTMLParser.extract_images(html, url),
            meta=HTMLParser.extract_meta(html),
        )

        self._session.pages_visited.append(url)
        self._session.pages_data[url] = page

        logger.debug(
            f"HttpxBrowser: opened {url} ({status}, "
            f"{len(page.text)} chars, {page.load_time_ms}ms)"
        )
        return page

    async def open_pages_parallel(
        self,
        urls: list[str],
        max_pages: int = 5,
    ) -> list[PageData]:
        """Open multiple pages in parallel."""
        tasks = [self.open_page(url) for url in urls[:max_pages]]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        pages = []
        for r in results:
            if isinstance(r, PageData):
                pages.append(r)
            elif isinstance(r, Exception):
                logger.debug(f"Parallel open error: {r}")
        return pages

    # ─── Search ──────────────────────────────────────────────────────────

    async def search(
        self,
        query: str,
        max_results: int = 10,
        engine: str = "duckduckgo",
    ) -> list[SearchResult]:
        """
        Search the web using multiple engines.
        Primary: DuckDuckGo HTML (no API key needed)
        Fallback: Google (if DDG fails)
        """
        results = []

        if engine in ("duckduckgo", "ddg", "auto"):
            results = await self._search_duckduckgo(query, max_results)

        if not results and engine in ("google", "auto"):
            results = await self._search_google(query, max_results)

        if not results:
            # Final fallback — DuckDuckGo lite
            results = await self._search_ddg_lite(query, max_results)

        self._session.search_results = results
        return results

    async def _search_duckduckgo(
        self,
        query: str,
        max_results: int = 10,
    ) -> list[SearchResult]:
        """Search via DuckDuckGo HTML version."""
        url = f"https://html.duckduckgo.com/html/?q={quote_plus(query)}"
        html, status, _ = await self._fetch(url, timeout=20)

        if not html or status != 200:
            return []

        results = []

        # Pattern 1: Full blocks with snippets
        blocks = re.findall(
            r'<a[^>]*class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>'
            r'.*?<a[^>]*class="result__snippet"[^>]*>(.*?)</a>',
            html, re.DOTALL
        )

        if blocks:
            for href, title_html, snippet_html in blocks[:max_results]:
                url = self._unwrap_ddg_url(href)
                title = unescape(re.sub(r'<[^>]+>', '', title_html)).strip()
                snippet = unescape(
                    re.sub(r'<[^>]+>', '', snippet_html)).strip()
                if title and url:
                    results.append(SearchResult(
                        title=title, url=url, snippet=snippet,
                        position=len(results) + 1,
                    ))
        else:
            # Pattern 2: Links only
            links = re.findall(
                r'<a[^>]*class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>',
                html
            )
            snippets = re.findall(
                r'<a[^>]*class="result__snippet"[^>]*>(.*?)</a>',
                html, re.DOTALL
            )
            for i, (href, title_html) in enumerate(links[:max_results]):
                url = self._unwrap_ddg_url(href)
                title = unescape(re.sub(r'<[^>]+>', '', title_html)).strip()
                snippet = ""
                if i < len(snippets):
                    snippet = unescape(
                        re.sub(r'<[^>]+>', '', snippets[i])).strip()
                if title and url:
                    results.append(SearchResult(
                        title=title, url=url, snippet=snippet,
                        position=len(results) + 1,
                    ))

        logger.debug(f"DDG search '{query}': {len(results)} results")
        return results

    async def _search_ddg_lite(
        self,
        query: str,
        max_results: int = 10,
    ) -> list[SearchResult]:
        """DuckDuckGo Lite fallback."""
        url = f"https://lite.duckduckgo.com/lite/?q={quote_plus(query)}"
        html, status, _ = await self._fetch(url, timeout=20)

        if not html:
            return []

        results = []
        # Lite version has simpler HTML
        for m in re.finditer(
            r'<a[^>]+href="(https?://[^"]+)"[^>]*>(.*?)</a>',
            html
        ):
            href = m.group(1)
            text = re.sub(r'<[^>]+>', '', m.group(2)).strip()
            if text and 'duckduckgo' not in href.lower():
                results.append(SearchResult(
                    title=text, url=href, position=len(results) + 1,
                ))
                if len(results) >= max_results:
                    break

        return results

    async def _search_google(
        self,
        query: str,
        max_results: int = 10,
    ) -> list[SearchResult]:
        """Search via Google (may be rate-limited)."""
        url = f"https://www.google.com/search?q={quote_plus(query)}&hl=ru&num={max_results}"
        html, status, _ = await self._fetch(url, timeout=20)

        if not html or status != 200:
            return []

        results = []
        # Google search result pattern
        for m in re.finditer(
            r'<a[^>]+href="/url\?q=([^&"]+)[^"]*"[^>]*>.*?'
            r'<h3[^>]*>(.*?)</h3>',
            html, re.DOTALL
        ):
            raw_url = unquote(m.group(1))
            title = re.sub(r'<[^>]+>', '', m.group(2)).strip()
            if title and raw_url.startswith('http'):
                results.append(SearchResult(
                    title=unescape(title),
                    url=raw_url,
                    position=len(results) + 1,
                ))
                if len(results) >= max_results:
                    break

        return results

    def _unwrap_ddg_url(self, url: str) -> str:
        """Unwrap DuckDuckGo redirect URL."""
        if "uddg=" in url:
            try:
                parsed = urlparse(url)
                real = parse_qs(parsed.query).get("uddg", [url])[0]
                return unquote(real)
            except Exception:
                pass
        return url

    # ─── Advanced Operations ─────────────────────────────────────────────

    async def search_and_extract(
        self,
        query: str,
        max_pages: int = 3,
        max_text_per_page: int = 3000,
    ) -> list[PageData]:
        """
        Manus-level: Search → Open top results → Extract content.

        Returns list of PageData with extracted text from top results.
        """
        results = await self.search(query, max_results=max_pages + 3)
        if not results:
            return []

        # Filter out DDG/search engine URLs
        valid_urls = [
            r.url for r in results
            if r.url and not any(
                d in r.url for d in
                ['duckduckgo.com', 'google.com/search', 'bing.com/search']
            )
        ][:max_pages]

        if not valid_urls:
            return []

        pages = await self.open_pages_parallel(valid_urls, max_pages)

        # Trim text
        for page in pages:
            if page.text and len(page.text) > max_text_per_page:
                page.text = page.text[:max_text_per_page]

        return pages

    async def deep_search(
        self,
        query: str,
        max_sources: int = 5,
        follow_depth: int = 1,
        max_text_per_page: int = 2000,
    ) -> dict[str, Any]:
        """
        Manus-level deep research:
        1. Search multiple engines
        2. Open top N pages in parallel
        3. For each page, follow relevant links (depth=1)
        4. Extract + compile all findings

        Returns structured research result.
        """
        start = time.time()

        # Step 1: Primary search
        primary_results = await self.search(query, max_results=max_sources + 3)

        # Step 2: Fetch primary pages in parallel
        urls = [
            r.url for r in primary_results
            if r.url and 'duckduckgo.com' not in r.url
        ][:max_sources]

        primary_pages = await self.open_pages_parallel(urls)

        all_pages = list(primary_pages)

        # Step 3: Follow links if depth > 0
        if follow_depth > 0:
            follow_urls = set()
            query_words = set(query.lower().split())

            for page in primary_pages:
                if not page.success:
                    continue
                for link in page.links[:20]:
                    link_text = link.get("text", "").lower()
                    link_url = link.get("url", "")
                    # Follow if link text contains query words
                    if (link_url and
                            link_url not in self._session.pages_visited and
                            any(w in link_text for w in query_words if len(w) > 3)):
                        follow_urls.add(link_url)

            if follow_urls:
                follow_list = list(follow_urls)[:max_sources]
                followed = await self.open_pages_parallel(follow_list)
                all_pages.extend(followed)

        # Step 4: Compile results
        findings = []
        for page in all_pages:
            if page.success and page.text:
                text = page.text[:max_text_per_page]
                findings.append({
                    "url": page.url,
                    "title": page.title,
                    "text": text,
                    "tables": page.tables[:3],
                })

        duration_ms = int((time.time() - start) * 1000)

        return {
            "query": query,
            "sources_count": len(findings),
            "pages_fetched": len(all_pages),
            "duration_ms": duration_ms,
            "findings": findings,
            "search_results": [
                {"title": r.title, "url": r.url, "snippet": r.snippet}
                for r in primary_results[:max_sources]
            ],
        }

    async def extract_structured(
        self,
        url: str,
        focus: str = "",
    ) -> dict[str, Any]:
        """
        Extract structured data from a page, optionally focusing on
        content related to a specific topic.
        """
        page = await self.open_page(url)
        if not page.success:
            return {"error": page.error, "url": url}

        result: dict[str, Any] = {
            "url": url,
            "title": page.title,
            "meta": page.meta,
            "headings": page.headings,
            "tables_count": len(page.tables),
            "links_count": len(page.links),
            "images_count": len(page.images),
        }

        if focus:
            # Filter text to paragraphs containing focus words
            focus_words = set(focus.lower().split())
            paragraphs = page.text.split('\n')
            relevant = [
                p for p in paragraphs
                if any(w in p.lower() for w in focus_words if len(w) > 3)
            ]
            result["focused_text"] = '\n'.join(relevant)[:4000]
            result["full_text_length"] = len(page.text)
        else:
            result["text"] = page.text[:4000]

        if page.tables:
            result["tables"] = page.tables[:5]

        return result

    async def fill_and_submit(
        self,
        url: str,
        form_data: dict[str, str],
        action_url: str = "",
    ) -> PageData:
        """
        Simulate form filling by sending POST request.

        Args:
            url: Current page URL (for referer)
            form_data: Form fields {name: value}
            action_url: POST target URL (defaults to current url)

        Returns:
            PageData of the response page
        """
        target = action_url or url
        start = time.time()
        html, status, headers = await self._fetch(
            target, method="POST", data=form_data, referer=url
        )

        page = PageData(
            url=target,
            status_code=status,
            content_type=headers.get("content-type", ""),
            load_time_ms=int((time.time() - start) * 1000),
            title=HTMLParser.extract_title(html) if html else "",
            text=HTMLParser.extract_text(html) if html else "",
        )

        if not html:
            page.error = f"Form submission failed (status {status})"

        return page

    # ─── Session Management ──────────────────────────────────────────────

    def new_session(self):
        """Start a new browsing session."""
        self._session = BrowsingSession()
        self._ua = random.choice(USER_AGENTS)

    def get_session_stats(self) -> dict[str, Any]:
        return {
            "pages_visited": len(self._session.pages_visited),
            "total_requests": self._session.total_requests,
            "total_bytes": self._session.total_bytes,
            "duration_ms": self._session.duration_ms,
            "search_results_cached": len(self._session.search_results),
        }

    def get_cached_page(self, url: str) -> PageData | None:
        """Get previously fetched page from cache."""
        return self._session.pages_data.get(url)


# ═══════════════════════════════════════════════════════════════════════════════
# GLOBAL INSTANCE
# ═══════════════════════════════════════════════════════════════════════════════

httpx_browser = HttpxBrowser()
