# Incentive Scraper — Claude Context

MVP pipeline for Dreamline AI: scrapes clean-energy / housing / hurricane-resilience incentive programs and writes a 12-column CSV. Default scope = Tampa + Hillsborough County, but the pipeline is region-configurable from the CLI.

## Architecture

```
Source registry → Extractor → LLM Parser (Groq Llama-3.3-70B) → Validator → CSV
                              └─ OR deterministic parser (DSIRE) ────────────┘
```

Extractors that expose `parse_records(source, region)` bypass the LLM and return record dicts directly. The DSIRE spider uses this path — saves Groq tokens, gives deterministic output, and applies the region filter at parse time.

No Postgres, no scheduler, no diff engine — those are deferred to later phases.

## Layout

- `config/regions.py` — region presets (`tampa_hillsborough`, `tampa_bay_msa`, `florida_statewide`) + CLI override resolution
- `config/sources.py` — 17 built-in sources + custom-source loader. Each tagged `applicable_states=["FL"]` or `["ALL"]`. Pipeline auto-skips sources whose states don't intersect the active region. Exposes `add_custom_source` / `remove_custom_source`.
- `config/custom_sources.json` — user-added sources (managed via `main.py add-source`); merged into `SOURCES` dict at import time.
- `extractors/html_extractor.py` — requests + Trafilatura + BeautifulSoup fallback for static pages
- `extractors/playwright_extractor.py` — headless Chromium for JS-rendered pages and sites that block plain requests. Uses `networkidle` wait with `domcontentloaded` fallback on timeout.
- `extractors/dsire_spider.py` — Two-pass DSIRE scraper. Uses Playwright `innerText` (not trafilatura) so JS-rendered label/value pairs survive. Parses `Incentive Amount`, `Maximum Incentive`, `Equipment Requirements`, `Applicable Sectors`, `Summary`, etc. into record dicts via `parse_records`. Region-filtered: keeps state/federal/territory programs always; only keeps utility/local programs whose Administrator or program name matches `region.cities`/`counties`/`utility_providers`. Stamps `state=source.default_state` (DSIRE's "Federal" classification is NOT used for the state column) and `city=region.cities[0]` for surviving records.
- `extractors/pdf_extractor.py` — pdfplumber for PDF documents
- `extractors/api_extractor.py` — JSON API fetcher (pretty-prints JSON for LLM)
- `extractors/apify_extractor.py` — Apify actor runner (DSIRE crawler, requires APIFY_TOKEN)
- `parsers/llm_parser.py` — `LLMClient` (Groq Llama-3.3-70B only). System prompt instructs Groq to return `{"programs": [...]}` wrapper; validator unwraps it.
- `parsers/schema.py` — Pydantic `IncentiveRecord` + `CSV_COLUMN_ORDER` + `GEMINI_RESPONSE_SCHEMA` (schema kept for reference; no longer used)
- `validators/validator.py` — coerces LLM quirks (lists → strings, `"null"` → None, year-only → `YYYY-12-31`, `rebate` → `Rebates` alias map), drops records with no `program_name` or invalid URL, flags `review_needed="Yes"` for missing/ambiguous fields.
- `pipeline/run.py` — orchestrator. Calls `extractor.parse_records(source, region)` if available (deterministic path); otherwise falls back to extract → LLM parse. Dedupes by (program_name, state), writes CSV in `CSV_COLUMN_ORDER`.
- `main.py` — argparse CLI with subcommands: default (run pipeline), `add-source`, `list-sources`, `remove-source`.
- `output/` — CSVs land here as `likitha_extracted_{region_slug}_incentives.csv`.

## Run

```bash
./venv/bin/python main.py                                        # default = tampa_hillsborough
./venv/bin/python main.py --region florida_statewide             # all FL sources
./venv/bin/python main.py --region tampa_bay_msa
./venv/bin/python main.py --state FL --zip 33602,33603
./venv/bin/python main.py --sources irs_energy_credits --dry-run

# Source management (no code edits required)
./venv/bin/python main.py list-sources
./venv/bin/python main.py add-source --key K --name N --url U --extractor html --states FL --default-city Tampa --admin "..."
./venv/bin/python main.py remove-source --key K
```

## Setup

1. `python -m venv venv && ./venv/bin/pip install -r requirements.txt`
2. `./venv/bin/python -m playwright install chromium`
3. Copy `.env.example` → `.env`, fill `GROQ_API_KEY` (required). `APIFY_TOKEN` optional (improves DSIRE scraping).
4. Run `main.py`.

## CSV Output Spec (authoritative — do not reorder columns)

```
program_name, state, city, incentive_type, property_type, description,
eligibility_criteria, incentive_amount, valid_until, updated_at,
review_needed, program_links
```

`incentive_type` ∈ {Grants, Rebates, Finance Solutions, Tax Credits, Investments}.
Only **active** programs (even if current application window is closed).
`review_needed="Yes"` if any required field missing/ambiguous.

## Sources Status (last checked 2026-05-06)

| Key | Priority | Status | Records (Tampa run) | Issue |
|---|---|---|---|---|
| `dsire_fl` | P0 | Working | 25 (8 review) | Deterministic parser via DSIRE spider; out-of-region utility/local programs filtered out |
| `rewiring_ira` | P0 | Working | ~10 | Missing eligibility_criteria → review_needed |
| `irs_energy_credits` | P0 | Working | 2 | Clean, no review needed |
| `teco_rebates` | P0 | Blocked | 0 | Site returns 930 chars even with Playwright — consent/bot detection |
| `doe_energy_saver` | P0 | Blocked | 0 | DOE blocks scrapers |
| `my_safe_fl_home` | P1 | Working | 1 | Missing eligibility → review_needed |
| `irs_energy_credits_detail` | P1 | Working | 1 | Clean |
| `duke_fl_rebates` | P1 | Blocked | 0 | 202 chars, bot detection |
| `fl_housing` | P1 | Blocked | 0 | 426 chars even with Playwright |
| `hillsborough_housing` | P1 | Blocked | 0 | 444 chars |
| `fl_solar_tax_exemptions` | P1 | Partial | 1 | Missing amount/eligibility |
| `fl_energy_programs` | P1 | Blocked | 0 | 103 chars |
| `city_tampa_dev` | P2 | Blocked | 0 | 409 chars |
| `fema_mitigation` | P2 | Partial | 1 | Missing amount |
| `ygrene_pace` | P2 | Blocked | 0 | 223 chars |
| `pace_florida` | P2 | Blocked | 0 | Empty |
| `doe_weatherization` | P2 | Partial | 1 | Missing amount |

## Known Limitations & Next Steps

- **TECO/Duke/FL Housing**: Bot detection persists even with Playwright. Options: Apify actor, residential proxy, or manual data entry.
- **Rewiring America**: IRA policy page gives 10 records but all lack `eligibility_criteria`. Consider fetching sub-pages per program.
- **DSIRE incentive_type defaults**: Programs whose DSIRE "Incentive Type" string isn't in `_DSIRE_TYPE_TO_SCHEMA` fall back to "Tax Credits". Extend the map in `dsire_spider.py` if you see misclassified rows.
- **Target**: 150+ validated records for Phase 1. Current: ~25 with `tampa_hillsborough`, ~50 with `florida_statewide`.

## Gotchas

- LLM is Groq Llama-3.3-70B only — Gemini removed. No fallback.
- Playwright extractor tries `networkidle` first, falls back to `domcontentloaded` on 45s timeout.
- DSIRE's "State" field is a *classification* (State/Federal/Local/Utility), NOT a US state name. The spider deliberately ignores it and uses `source.default_state` ("Florida") for the `state` column.
- The validator's alias map (e.g. `rebate` → `Rebates`) normalizes Groq output since Groq doesn't enforce enums.
- Adding a new state = add a region preset in `config/regions.py` + add state-tagged sources (built-in via `config/sources.py`, or custom via `main.py add-source`).
- Custom sources cannot use a key that collides with a built-in source. Built-in keys can't be removed via CLI either — edit `config/sources.py` directly.

## Out of Scope

PostgreSQL, Celery scheduler, diff engine, human review UI, source-discovery agent, FastAPI layer, confidence scoring. All deferred.
