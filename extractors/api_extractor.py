import json

import requests
import structlog
from tenacity import retry, stop_after_attempt, wait_exponential

from config.sources import SourceConfig
from extractors.base import BaseExtractor, RawDoc

log = structlog.get_logger()


class ApiExtractor(BaseExtractor):
    """Generic JSON-API fetcher. Stuffs the JSON response (pretty-printed) into
    RawDoc.text so the LLM parser can extract programs from it like any other doc.
    """

    timeout = 30

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=2, max=10))
    def _fetch_json(self, url: str, params: dict | None) -> dict | list:
        self._throttle()
        resp = requests.get(
            url,
            params=params or {},
            headers={"User-Agent": self.user_agent, "Accept": "application/json"},
            timeout=self.timeout,
        )
        resp.raise_for_status()
        return resp.json()

    def extract(self, source: SourceConfig) -> RawDoc:
        log.info("api_extract.fetch", source=source.key, url=source.url)
        try:
            data = self._fetch_json(source.url, source.api_params)
        except Exception as e:
            log.error("api_extract.fetch_failed", source=source.key, error=str(e))
            return RawDoc(source.key, source.url, "", self.today_iso())

        text = json.dumps(data, indent=2)[:120_000]  # cap to keep LLM context sane
        log.info("api_extract.done", source=source.key, chars=len(text))
        return RawDoc(source.key, source.url, text, self.today_iso())
