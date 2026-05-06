import structlog
import trafilatura
from bs4 import BeautifulSoup

from config.sources import SourceConfig
from extractors.base import BaseExtractor, RawDoc

log = structlog.get_logger()

_WAIT_MS = 2000
_MAX_PROGRAMS = 50
_BATCH_SIZE = 5  # programs per LLM call — keeps token usage under Groq free-tier daily limit


class DSIRESpiderExtractor(BaseExtractor):
    """Two-pass DSIRE scraper.

    Pass 1: Playwright renders the FL program list → extracts all detail URLs.
    Pass 2: Playwright renders each detail page → batches N programs per RawDoc.

    Returns batched RawDocs (BATCH_SIZE programs each) so the pipeline makes
    ceil(N/BATCH_SIZE) LLM calls instead of N, staying within Groq's 100K TPD limit.
    """

    def extract(self, source: SourceConfig) -> RawDoc:
        docs = self.extract_many(source)
        if not docs:
            return RawDoc(source.key, source.url, "", self.today_iso())
        return docs[0]

    def extract_many(self, source: SourceConfig) -> list[RawDoc]:
        from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

        log.info("dsire_spider.start", source=source.key)

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            ctx = browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0.0.0 Safari/537.36"
                ),
                ignore_https_errors=True,
            )
            page = ctx.new_page()

            # Pass 1 — get program list
            detail_urls = self._get_detail_urls(page, source.url)
            log.info("dsire_spider.urls_found", count=len(detail_urls))

            # Pass 2 — fetch each detail page, collect texts
            pages: list[tuple[str, str]] = []  # (url, text)
            for i, url in enumerate(detail_urls[:_MAX_PROGRAMS]):
                self._throttle()
                try:
                    try:
                        page.goto(url, wait_until="networkidle", timeout=30_000)
                    except PWTimeout:
                        page.goto(url, wait_until="domcontentloaded", timeout=20_000)
                    page.wait_for_timeout(_WAIT_MS)
                    html = page.content()
                    text = self._extract_text(html)
                    if len(text.strip()) >= 100:
                        pages.append((url, text))
                        log.info("dsire_spider.page_ok", index=i + 1, chars=len(text))
                    else:
                        log.warning("dsire_spider.page_empty", index=i + 1, url=url)
                except Exception as e:
                    log.warning("dsire_spider.page_failed", url=url, error=str(e))

            browser.close()

        # Batch pages into groups — one RawDoc per batch → one LLM call per batch
        batched_docs: list[RawDoc] = []
        for batch_start in range(0, len(pages), _BATCH_SIZE):
            batch = pages[batch_start: batch_start + _BATCH_SIZE]
            combined = "\n\n".join(
                f"=== PROGRAM {batch_start + j + 1} | {url} ===\n{text}"
                for j, (url, text) in enumerate(batch)
            )
            batched_docs.append(RawDoc(source.key, source.url, combined[:80_000], self.today_iso()))

        log.info(
            "dsire_spider.done",
            source=source.key,
            pages=len(pages),
            batches=len(batched_docs),
        )
        return batched_docs

    def _get_detail_urls(self, page, list_url: str) -> list[str]:
        from playwright.sync_api import TimeoutError as PWTimeout
        try:
            page.goto(list_url, wait_until="networkidle", timeout=45_000)
        except PWTimeout:
            page.goto(list_url, wait_until="domcontentloaded", timeout=30_000)
        page.wait_for_timeout(3000)

        links = page.eval_on_selector_all(
            "a",
            "els => els.map(e => e.href)",
        )
        seen: set[str] = set()
        result: list[str] = []
        for url in links:
            if "/system/program/detail/" in url and url not in seen:
                seen.add(url)
                result.append(url)
        return result

    def _extract_text(self, html: str) -> str:
        text = trafilatura.extract(html, include_tables=True, include_links=True) or ""
        if len(text.strip()) < 200:
            soup = BeautifulSoup(html, "lxml")
            for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
                tag.decompose()
            text = soup.get_text(separator="\n", strip=True)
        return text
