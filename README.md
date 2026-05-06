# AI Incentive Web Scraper Agent

Structured AI scraping pipeline for the Dreamline AI incentive database. Pulls clean-energy / housing / hurricane-resilience incentive programs from federal, state, county, city, and utility sources and writes a 12-column CSV matching the Dreamline AI extraction spec.

Architecture: **Source registry → Extractor → LLM Parser (Groq) → Validator → CSV.**

Built for the Tampa Bay launch market, expandable to all of Florida and beyond.

## Setup

```bash
cd Incentive_Scraper
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python -m playwright install chromium

cp .env.example .env
# Edit .env, add GROQ_API_KEY (free at https://console.groq.com/keys)
# Optional: APIFY_TOKEN for DSIRE Apify actor fallback
```

## Usage

```bash
# Default: tampa_hillsborough region, all applicable sources
python main.py

# Florida statewide — recommended for full coverage
python main.py --region florida_statewide

# Smoke test — single source, no CSV write
python main.py --sources irs_energy_credits --dry-run

# DSIRE deep scrape only (50 detail pages, batched into 10 LLM calls)
python main.py --sources dsire_fl

# Custom region
python main.py --state FL --zip 33602,33603,33604
```

## Output

CSV → `output/likitha_extracted_<region>_incentives.csv`

Columns (exact order required by spec):
`program_name, state, city, incentive_type, property_type, description, eligibility_criteria, incentive_amount, valid_until, updated_at, review_needed, program_links`

`incentive_type` ∈ `{Grants, Rebates, Finance Solutions, Tax Credits, Investments}`.
`review_needed = "Yes"` when any field is missing/ambiguous.

## Extractors

| Type | Use case |
|---|---|
| `html` | Static pages — requests + Trafilatura + BeautifulSoup fallback |
| `playwright` | JS-rendered pages and sites that block plain requests |
| `pdf` | Government PDF documents — pdfplumber |
| `api` | JSON APIs — pretty-prints response for LLM |
| `apify` | Apify actors (DSIRE crawler with `APIFY_TOKEN`) |
| `dsire_spider` | Two-pass DSIRE scraper: list page → up to 75 detail pages → deterministic field parser (no LLM, region-filtered) |

## Sources (17 configured)

**P0 (high priority):** DSIRE Florida (50 programs via spider), Rewiring America IRA, IRS Home Energy Credits, TECO Rebates, DOE Energy Saver
**P1:** My Safe Florida Home, IRS 25C detail, Duke Energy FL, Florida Housing FC, Hillsborough County Housing, Florida Solar Tax Exemptions, Florida Energy Programs (DEO)
**P2:** City of Tampa Community Development, FEMA Hazard Mitigation, Ygrene PACE, Florida PACE Funding Agency, DOE Weatherization

Some utility sites (TECO, Duke, FL Housing portal) actively block scrapers; these need an Apify residential proxy or manual entry.

## Adding a new source

You have two options:

**1. CLI (no code changes) — recommended for one-offs.** Custom sources are stored in `config/custom_sources.json` and merged into the registry on every run.

```bash
# Add
python main.py add-source \
  --key tampa_solar_coop \
  --name "Tampa Solar United Neighbors Co-op" \
  --url "https://www.solarunitedneighbors.org/florida/" \
  --extractor html \
  --priority P2 \
  --states FL \
  --default-city Tampa \
  --admin "Solar United Neighbors"

# Use it immediately
python main.py --sources tampa_solar_coop --dry-run

# List everything (built-in + custom)
python main.py list-sources

# Remove a custom source
python main.py remove-source --key tampa_solar_coop
```

`--extractor` ∈ `html` / `playwright` / `pdf` / `api` / `apify` / `dsire_spider`.
`--states` is comma-separated (`FL`, `FL,GA`) or `ALL` for federal.
Built-in source keys cannot be overridden or removed via CLI.

**2. Edit `config/sources.py`** — add a `SourceConfig` to the dict for permanent built-in sources you want tracked in git.

## Adding a new region

Edit `config/regions.py` — add a `Region` entry to `REGIONS`. Or pass `--state` and `--zip` directly on the CLI.

## Project layout

```
Incentive_Scraper/
├── main.py                       # CLI
├── config/
│   ├── regions.py                # Region presets (tampa_hillsborough, tampa_bay_msa, florida_statewide)
│   ├── sources.py                # 17-source built-in registry + custom-source loader/writer
│   └── custom_sources.json       # User-added sources (managed by `main.py add-source`)
├── extractors/
│   ├── base.py                   # ABC, rate limiting, retries
│   ├── html_extractor.py         # requests + Trafilatura + BS4 fallback
│   ├── playwright_extractor.py   # Headless Chromium for JS pages / blocked sites
│   ├── dsire_spider.py           # Two-pass DSIRE list → 50 detail pages, batched
│   ├── pdf_extractor.py          # pdfplumber
│   ├── api_extractor.py          # Generic JSON
│   └── apify_extractor.py        # Apify actor runner
├── parsers/
│   ├── schema.py                 # Pydantic IncentiveRecord + CSV column order
│   └── llm_parser.py             # Groq Llama-3.3-70B parser
├── validators/
│   └── validator.py              # Schema check, alias normalization, sets review_needed
├── pipeline/
│   └── run.py                    # Orchestrator (handles extract_many for spiders)
└── output/                       # CSVs land here
```

## LLM

Groq Llama-3.3-70B (free tier — 100K tokens/day). The DSIRE spider batches 5 programs per LLM call to stay within the daily quota.

## Out of scope (MVP)

PostgreSQL storage, Celery scheduler, diff/change-detection engine, human-review UI, source-discovery agent, FastAPI layer. These layer on top later without changing extractor/parser code.
