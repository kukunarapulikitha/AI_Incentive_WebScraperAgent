import structlog
import trafilatura
from bs4 import BeautifulSoup

from config.sources import SourceConfig
from extractors.base import BaseExtractor, RawDoc

log = structlog.get_logger()

_WAIT_MS = 3000  # ms to wait after page load for JS to render


class PlaywrightExtractor(BaseExtractor):
    """Headless Chromium extractor for JS-rendered pages that block plain requests."""

    def extract(self, source: SourceConfig) -> RawDoc:
        log.info("playwright_extract.fetch", source=source.key, url=source.url)
        try:
            html = self._fetch_with_browser(source.url)
        except Exception as e:
            log.error("playwright_extract.fetch_failed", source=source.key, error=str(e))
            return RawDoc(source.key, source.url, "", self.today_iso())

        text = trafilatura.extract(html, include_tables=True, include_links=True) or ""
        if len(text.strip()) < 200:
            soup = BeautifulSoup(html, "lxml")
            for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
                tag.decompose()
            text = soup.get_text(separator="\n", strip=True)

        log.info("playwright_extract.done", source=source.key, chars=len(text))
        return RawDoc(source.key, source.url, text, self.today_iso())

    def _fetch_with_browser(self, url: str) -> str:
        from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            ctx = browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0.0.0 Safari/537.36"
                ),
                ignore_https_errors=True,
                locale="en-US",
            )
            page = ctx.new_page()
            # Try networkidle first; fall back to domcontentloaded on timeout
            try:
                page.goto(url, wait_until="networkidle", timeout=45_000)
            except PWTimeout:
                page.goto(url, wait_until="domcontentloaded", timeout=30_000)
            page.wait_for_timeout(_WAIT_MS)
            html = page.content()
            browser.close()
        return html
