import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timezone

from config.sources import SourceConfig


@dataclass
class RawDoc:
    source_key: str
    url: str
    text: str
    fetched_at: str  # ISO YYYY-MM-DD


class BaseExtractor(ABC):
    user_agent = (
        "DreamlineAI-IncentiveScraper/0.1 "
        "(+https://dreamlineai.org; contact: kukunarapu.l@northeastern.edu)"
    )
    rate_limit_seconds = 1.0
    _last_request_at: float = 0.0

    def _throttle(self) -> None:
        elapsed = time.time() - self._last_request_at
        wait = self.rate_limit_seconds - elapsed
        if wait > 0:
            time.sleep(wait)
        self._last_request_at = time.time()

    @staticmethod
    def today_iso() -> str:
        return datetime.now(timezone.utc).date().isoformat()

    @abstractmethod
    def extract(self, source: SourceConfig) -> RawDoc:
        ...
