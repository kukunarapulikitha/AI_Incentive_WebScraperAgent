from collections import Counter
from pathlib import Path

import pandas as pd
import structlog

from config.regions import Region
from config.sources import SourceConfig, select_sources
from extractors import get_extractor
from extractors.static_extractor import StaticExtractor
from parsers.llm_parser import LLMClient, parse_doc
from parsers.schema import CSV_COLUMN_ORDER, IncentiveRecord
from validators.validator import validate

log = structlog.get_logger()

# Map two-letter state codes to the full state name we want in the CSV.
# Extend as we add more regions.
_STATE_CODE_TO_NAME = {
    "FL": "Florida",
    "CA": "California",
    "TX": "Texas",
    "NY": "New York",
    "GA": "Georgia",
}


def _stamp_region(rec: IncentiveRecord, region: Region) -> IncentiveRecord:
    """Override `state` and `city` on every record so the CSV consistently
    reflects the region the user is filtering for.

    Why: federal sources (IRS, FEMA, DOE, Rewiring America) have
    `default_state="USA"`, which the LLM then copies into `state`. But if
    you're scraping for Tampa, every record in the output is — by
    definition — applicable to Florida/Tampa, so the CSV should say so.
    "USA" / "Federal" / "All States" are program-classification labels,
    not values that belong in a `state` column scoped to a region.
    """
    if region.state:
        full_name = _STATE_CODE_TO_NAME.get(region.state.upper(), region.state)
        rec.state = full_name
    if region.cities:
        rec.city = region.cities[0]
    return rec


def _dedupe(records: list[IncentiveRecord]) -> list[IncentiveRecord]:
    seen: set[tuple[str, str]] = set()
    out: list[IncentiveRecord] = []
    for r in records:
        key = (r.program_name.strip().lower(), r.state.strip().lower())
        if key in seen:
            continue
        seen.add(key)
        out.append(r)
    return out


def run(
    region: Region,
    only_sources: list[str] | None = None,
    limit_per_source: int | None = None,
    llm_provider: str | None = None,
    dry_run: bool = False,
    output_dir: Path | None = None,
) -> tuple[list[IncentiveRecord], Path | None]:
    sources: list[SourceConfig] = select_sources(region.state, only_sources)
    log.info("pipeline.start", region=region.slug, n_sources=len(sources))

    client = LLMClient(force_provider=llm_provider)
    static_fallback = StaticExtractor()
    all_records: list[IncentiveRecord] = []
    per_source: Counter[str] = Counter()

    def _ingest(records: list[dict], source_key: str) -> int:
        """Validate, region-stamp, and append. Returns count added."""
        added = 0
        if limit_per_source:
            records = records[:limit_per_source]
        for d in records:
            rec = validate(d)
            if rec is None:
                continue
            _stamp_region(rec, region)
            all_records.append(rec)
            per_source[source_key] += 1
            added += 1
        return added

    for source in sources:
        added_for_source = 0
        try:
            extractor = get_extractor(source)

            # Path 1: extractors that pre-parse records (DSIRE spider,
            # StaticExtractor) skip the LLM entirely.
            if hasattr(extractor, "parse_records"):
                raw_records = extractor.parse_records(source, region)
                added_for_source += _ingest(raw_records, source.key)
            else:
                # Path 2: extract → LLM parse.
                if hasattr(extractor, "extract_many"):
                    raws = extractor.extract_many(source)
                else:
                    raws = [extractor.extract(source)]
                for raw in raws:
                    try:
                        raw_records = parse_doc(raw, source, region, client)
                    except Exception as parse_err:
                        log.warning(
                            "pipeline.llm_parse_failed",
                            source=source.key,
                            error=str(parse_err),
                        )
                        raw_records = []
                    added_for_source += _ingest(raw_records, source.key)
        except Exception as e:
            log.error("pipeline.source_failed", source=source.key, error=str(e))

        # Dynamic fallback: if the primary path produced no records (LLM rate
        # limit, bot detection, network error, missing API key, etc.) and we
        # have curated static records for this source, use them. Lets the
        # pipeline always emit a complete CSV without depending on Groq quota
        # or fragile utility/government-site scrapers.
        if added_for_source == 0 and not isinstance(extractor, StaticExtractor):
            try:
                static_records = static_fallback.parse_records(source, region)
            except Exception as e:
                log.warning("pipeline.static_fallback_failed", source=source.key, error=str(e))
                static_records = []
            if static_records:
                log.info(
                    "pipeline.static_fallback",
                    source=source.key,
                    n=len(static_records),
                )
                _ingest(static_records, source.key)

    deduped = _dedupe(all_records)
    review_count = sum(1 for r in deduped if r.review_needed == "Yes")
    log.info(
        "pipeline.done",
        total=len(deduped),
        before_dedupe=len(all_records),
        review_needed=review_count,
        per_source=dict(per_source),
    )

    if dry_run:
        return deduped, None

    output_dir = output_dir or (Path(__file__).resolve().parent.parent / "output")
    output_dir.mkdir(parents=True, exist_ok=True)
    filename = f"likitha_extracted_{region.slug.replace('tampa_hillsborough', 'tampa')}_incentives.csv"
    out_path = output_dir / filename

    df = pd.DataFrame([r.model_dump() for r in deduped], columns=CSV_COLUMN_ORDER)
    df.to_csv(out_path, index=False)
    log.info("pipeline.csv_written", path=str(out_path), rows=len(df))
    return deduped, out_path
