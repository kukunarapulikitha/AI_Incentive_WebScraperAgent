import argparse
import sys

import structlog
from dotenv import load_dotenv

from config.regions import REGIONS, build_region
from config.sources import (
    BUILTIN_SOURCES,
    SOURCES,
    SourceConfig,
    VALID_EXTRACTOR_TYPES,
    VALID_PRIORITIES,
    add_custom_source,
    remove_custom_source,
)
from pipeline.run import run

load_dotenv()
structlog.configure(processors=[structlog.processors.KeyValueRenderer()])
log = structlog.get_logger()

SUBCOMMANDS = {"add-source", "list-sources", "remove-source"}


def parse_run_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Dreamline AI — Incentive scraper. Pulls incentive programs from "
        "configured sources, normalizes via LLM (or deterministic parser), writes a "
        "12-column CSV.",
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
        help=f"Comma-separated source keys. Available: {','.join(sorted(SOURCES))}",
    )
    p.add_argument("--limit", type=int, default=None, help="Max records per source (smoke test).")
    p.add_argument("--llm", choices=["groq"], default=None, help="Force LLM provider.")
    p.add_argument("--dry-run", action="store_true", help="Skip CSV write.")
    return p.parse_args(argv)


def parse_add_source_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="main.py add-source",
        description="Register a new incentive source. Stored in config/custom_sources.json "
        "(merged into the in-memory registry on every run).",
    )
    p.add_argument("--key", required=True, help="Unique source key (e.g. 'tampa_solar_coop').")
    p.add_argument("--name", required=True, help="Human-readable program/source name.")
    p.add_argument("--url", required=True, help="Page URL the extractor should hit.")
    p.add_argument(
        "--extractor",
        required=True,
        choices=sorted(VALID_EXTRACTOR_TYPES),
        help="Which extractor handles this source.",
    )
    p.add_argument(
        "--priority",
        default="P1",
        choices=sorted(VALID_PRIORITIES),
        help="P0 = launch-critical, P1 = high value, P2 = nice-to-have.",
    )
    p.add_argument(
        "--states",
        default="ALL",
        help="Comma-separated state codes the source applies to, or 'ALL' for federal/national. "
        "Default: ALL.",
    )
    p.add_argument(
        "--default-state",
        default=None,
        help="State name to stamp on records when the LLM/parser leaves it blank. "
        "Defaults to 'USA' for ALL, else the first listed state.",
    )
    p.add_argument("--default-city", default=None, help="Default city to stamp on records.")
    p.add_argument(
        "--admin",
        dest="default_administrator",
        default=None,
        help="Program administrator name (e.g. 'Tampa Electric').",
    )
    p.add_argument("--notes", default="", help="Free-form scraping notes.")
    p.add_argument(
        "--overwrite",
        action="store_true",
        help="Replace an existing custom source with the same key (built-in keys cannot be overridden).",
    )
    return p.parse_args(argv)


def parse_remove_source_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="main.py remove-source",
        description="Remove a custom source from config/custom_sources.json. "
        "Built-in sources cannot be removed.",
    )
    p.add_argument("--key", required=True, help="Custom source key to remove.")
    return p.parse_args(argv)


def cmd_run(argv: list[str]) -> int:
    args = parse_run_args(argv)

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


def cmd_add_source(argv: list[str]) -> int:
    args = parse_add_source_args(argv)

    states = [s.strip().upper() for s in args.states.split(",") if s.strip()]
    if not states:
        states = ["ALL"]
    default_state = args.default_state or ("USA" if "ALL" in states else states[0])

    cfg = SourceConfig(
        key=args.key,
        name=args.name,
        url=args.url,
        extractor_type=args.extractor,
        priority=args.priority,
        applicable_states=states,
        default_state=default_state,
        default_city=args.default_city,
        default_administrator=args.default_administrator,
        notes=args.notes or "",
    )
    try:
        add_custom_source(cfg, overwrite=args.overwrite)
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1

    print(f"Added custom source {cfg.key!r}.")
    print(f"  name:        {cfg.name}")
    print(f"  url:         {cfg.url}")
    print(f"  extractor:   {cfg.extractor_type}")
    print(f"  priority:    {cfg.priority}")
    print(f"  states:      {','.join(cfg.applicable_states)}")
    print(f"  default:     state={cfg.default_state}  city={cfg.default_city or '-'}")
    print()
    print(f"Try it:  python main.py --sources {cfg.key} --dry-run")
    return 0


def cmd_remove_source(argv: list[str]) -> int:
    args = parse_remove_source_args(argv)
    if args.key in BUILTIN_SOURCES:
        print(
            f"error: {args.key!r} is a built-in source and cannot be removed via CLI. "
            f"Edit config/sources.py if you really want to drop it.",
            file=sys.stderr,
        )
        return 1
    removed = remove_custom_source(args.key)
    if not removed:
        print(f"error: no custom source with key {args.key!r}.", file=sys.stderr)
        return 1
    print(f"Removed custom source {args.key!r}.")
    return 0


def cmd_list_sources(argv: list[str]) -> int:
    if argv and argv[0] in {"-h", "--help"}:
        print("usage: main.py list-sources")
        print("Print all sources (built-in + custom) grouped by origin.")
        return 0

    custom_keys = set(SOURCES) - set(BUILTIN_SOURCES)
    print(f"Built-in sources ({len(BUILTIN_SOURCES)}):")
    for key, src in BUILTIN_SOURCES.items():
        states = ",".join(src.applicable_states)
        print(f"  [{src.priority}] {key:32} {src.extractor_type:14} states={states:6} {src.name}")

    if custom_keys:
        print()
        print(f"Custom sources ({len(custom_keys)}):")
        for key in sorted(custom_keys):
            src = SOURCES[key]
            states = ",".join(src.applicable_states)
            print(f"  [{src.priority}] {key:32} {src.extractor_type:14} states={states:6} {src.name}")
    else:
        print()
        print("Custom sources: (none — add one with `python main.py add-source ...`)")
    return 0


def main() -> int:
    if len(sys.argv) > 1 and sys.argv[1] in SUBCOMMANDS:
        cmd = sys.argv[1]
        rest = sys.argv[2:]
        if cmd == "add-source":
            return cmd_add_source(rest)
        if cmd == "remove-source":
            return cmd_remove_source(rest)
        if cmd == "list-sources":
            return cmd_list_sources(rest)
    return cmd_run(sys.argv[1:])


if __name__ == "__main__":
    sys.exit(main())
