import argparse
import sys

import structlog
from dotenv import load_dotenv

from config.regions import REGIONS, build_region
from config.sources import SOURCES
from pipeline.run import run

load_dotenv()
structlog.configure(processors=[structlog.processors.KeyValueRenderer()])
log = structlog.get_logger()


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Dreamline AI — Incentive scraper. Pulls incentive programs from "
        "configured sources, normalizes via LLM, writes 12-column CSV.",
    )
    p.add_argument(
        "--region",
        choices=list(REGIONS.keys()),
        default=None,
        help="Region preset (default: tampa_hillsborough).",
    )
    p.add_argument("--state", default=None, help="State code, e.g. FL, CA. Overrides region default.")
    p.add_argument("--zip", dest="zip_codes", default=None, help="Comma-separated ZIP codes.")
    p.add_argument(
        "--sources",
        default=None,
        help=f"Comma-separated source keys. Available: {','.join(SOURCES)}",
    )
    p.add_argument("--limit", type=int, default=None, help="Max records per source (smoke test).")
    p.add_argument("--llm", choices=["groq"], default=None, help="Force LLM provider.")
    p.add_argument("--dry-run", action="store_true", help="Skip CSV write.")
    return p.parse_args()


def main() -> int:
    args = parse_args()

    region = build_region(
        region_key=args.region,
        state=args.state,
        zip_codes=args.zip_codes.split(",") if args.zip_codes else None,
    )
    only_sources = args.sources.split(",") if args.sources else None

    log.info(
        "main.config",
        region=region.slug,
        state=region.state,
        zip_codes=region.zip_codes,
        sources=only_sources or "ALL",
        limit=args.limit,
        llm=args.llm or "auto",
        dry_run=args.dry_run,
    )

    records, out_path = run(
        region=region,
        only_sources=only_sources,
        limit_per_source=args.limit,
        llm_provider=args.llm,
        dry_run=args.dry_run,
    )

    print()
    print(f"Extracted {len(records)} incentive programs")
    print(f"  Review needed: {sum(1 for r in records if r.review_needed == 'Yes')}")
    if out_path:
        print(f"  CSV: {out_path}")
    else:
        print("  CSV: (dry-run, skipped)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
