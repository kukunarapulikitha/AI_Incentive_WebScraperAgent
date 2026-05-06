from collections import Counter
from pathlib import Path

import pandas as pd
import structlog

from config.regions import Region
from config.sources import SourceConfig, select_sources
from extractors import get_extractor
from parsers.llm_parser import LLMClient, parse_doc
from parsers.schema import CSV_COLUMN_ORDER, IncentiveRecord
from validators.validator import validate

log = structlog.get_logger()


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
    all_records: list[IncentiveRecord] = []
    per_source: Counter[str] = Counter()

    for source in sources:
        try:
            extractor = get_extractor(source)
            # Spider extractors return multiple docs (one per program page)
            if hasattr(extractor, "extract_many"):
                raws = extractor.extract_many(source)
            else:
                raws = [extractor.extract(source)]

            for raw in raws:
                raw_records = parse_doc(raw, source, region, client)
                if limit_per_source:
                    raw_records = raw_records[:limit_per_source]
                for d in raw_records:
                    rec = validate(d)
                    if rec is None:
                        continue
                    all_records.append(rec)
                    per_source[source.key] += 1
        except Exception as e:
            log.error("pipeline.source_failed", source=source.key, error=str(e))

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
