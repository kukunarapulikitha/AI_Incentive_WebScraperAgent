import json
from pathlib import Path

import structlog

from config.regions import Region
from config.sources import SourceConfig
from extractors.base import BaseExtractor, RawDoc

log = structlog.get_logger()

_STATIC_RECORDS_PATH = Path(__file__).resolve().parent.parent / "config" / "static_records.json"


class StaticExtractor(BaseExtractor):
    """Emit pre-defined records from `config/static_records.json` — no HTTP, no LLM.

    Used for federal/state programs whose amounts and eligibility are stable,
    well-documented, and (often) published on sites that block scrapers (DOE,
    Duke, TECO, Florida Housing). Bypasses both bot detection and LLM rate
    limits.

    The JSON is a dict keyed by source.key. Each entry is a list of record
    dicts matching the IncentiveRecord schema. Records flow through the same
    validator/region-stamp path as LLM-parsed records.
    """

    def extract(self, source: SourceConfig) -> RawDoc:
        # No-op for compatibility — pipeline routes through parse_records.
        return RawDoc(source.key, source.url, "", self.today_iso())

    def parse_records(
        self,
        source: SourceConfig,
        region: Region | None = None,
    ) -> list[dict]:
        if not _STATIC_RECORDS_PATH.exists():
            log.warning("static_extractor.no_file", path=str(_STATIC_RECORDS_PATH))
            return []
        try:
            data = json.loads(_STATIC_RECORDS_PATH.read_text())
        except json.JSONDecodeError as e:
            log.error("static_extractor.bad_json", error=str(e))
            return []
        records = data.get(source.key, [])
        if not records:
            log.warning("static_extractor.no_records_for_key", source=source.key)
            return []

        # Default updated_at to today if missing on any record
        today = self.today_iso()
        for rec in records:
            rec.setdefault("updated_at", today)
            rec.setdefault("review_needed", "No")

        log.info("static_extractor.loaded", source=source.key, n=len(records))
        return list(records)
