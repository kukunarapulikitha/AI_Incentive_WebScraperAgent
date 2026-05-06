import requests
import structlog
import trafilatura
from bs4 import BeautifulSoup
from tenacity import retry, stop_after_attempt, wait_exponential

from config.sources import SourceConfig
from extractors.base import BaseExtractor, RawDoc

log = structlog.get_logger()


class HtmlExtractor(BaseExtractor):
    """Static HTML extractor: requests + Trafilatura main-content extraction.

    Falls back to BeautifulSoup get_text() if Trafilatura returns empty.
    """

    timeout = 30

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=2, max=10))
    def _fetch(self, url: str) -> str:
        self._throttle()
        resp = requests.get(
            url,
            headers={"User-Agent": self.user_agent, "Accept": "text/html,application/xhtml+xml"},
            timeout=self.timeout,
        )
        resp.raise_for_status()
        return resp.text

    def extract(self, source: SourceConfig) -> RawDoc:
        log.info("html_extract.fetch", source=source.key, url=source.url)
        try:
            html = self._fetch(source.url)
        except Exception as e:
            log.error("html_extract.fetch_failed", source=source.key, error=str(e))
            return RawDoc(source.key, source.url, "", self.today_iso())

        text = trafilatura.extract(html, include_tables=True, include_links=True) or ""
        if len(text.strip()) < 200:
            soup = BeautifulSoup(html, "lxml")
            for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
                tag.decompose()
            text = soup.get_text(separator="\n", strip=True)

        log.info("html_extract.done", source=source.key, chars=len(text))
        return RawDoc(source.key, source.url, text, self.today_iso())
