import io

import pdfplumber
import requests
import structlog
from tenacity import retry, stop_after_attempt, wait_exponential

from config.sources import SourceConfig
from extractors.base import BaseExtractor, RawDoc

log = structlog.get_logger()


class PdfExtractor(BaseExtractor):
    timeout = 60

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=2, max=10))
    def _download(self, url: str) -> bytes:
        self._throttle()
        resp = requests.get(url, headers={"User-Agent": self.user_agent}, timeout=self.timeout)
        resp.raise_for_status()
        return resp.content

    def extract(self, source: SourceConfig) -> RawDoc:
        log.info("pdf_extract.fetch", source=source.key, url=source.url)
        try:
            data = self._download(source.url)
        except Exception as e:
            log.error("pdf_extract.fetch_failed", source=source.key, error=str(e))
            return RawDoc(source.key, source.url, "", self.today_iso())

        chunks: list[str] = []
        with pdfplumber.open(io.BytesIO(data)) as pdf:
            for page in pdf.pages:
                t = page.extract_text() or ""
                if t.strip():
                    chunks.append(t)
                for tbl in page.extract_tables():
                    chunks.append("\n".join(["\t".join(c or "" for c in row) for row in tbl]))

        text = "\n\n".join(chunks)
        log.info("pdf_extract.done", source=source.key, chars=len(text))
        return RawDoc(source.key, source.url, text, self.today_iso())
