import re
from datetime import datetime

import structlog

from config.regions import Region
from config.sources import SourceConfig
from extractors.base import BaseExtractor, RawDoc

log = structlog.get_logger()

_WAIT_MS = 2500
_MAX_PROGRAMS = 75

# DSIRE labels we capture as structured fields. Each label is a heading line in
# the rendered detail page; the next non-empty line(s) are the value.
_LABELS = [
    "Implementing Sector",
    "Category",
    "State",
    "Incentive Type",
    "Administrator",
    "Start Date",
    "Expiration Date",
    "Eligible Renewable/Other Technologies",
    "Eligible Efficiency Technologies",
    "Applicable Sectors",
    "Incentive Amount",
    "Maximum Incentive",
    "Equipment Requirements",
    "Installation Requirements",
    "Ownership of Renewable Energy Credits",
    "Eligible System Size",
    "Program Budget",
]
_LABEL_SET = {lbl + ":" for lbl in _LABELS}

# Map DSIRE's "Incentive Type" string → our schema vocab
_DSIRE_TYPE_TO_SCHEMA = {
    "sales tax incentive": "Tax Credits",
    "personal tax credit": "Tax Credits",
    "corporate tax credit": "Tax Credits",
    "property tax incentive": "Tax Credits",
    "property tax assessment": "Tax Credits",
    "income tax credit": "Tax Credits",
    "rebate program": "Rebates",
    "rebate": "Rebates",
    "grant program": "Grants",
    "grant": "Grants",
    "loan program": "Finance Solutions",
    "pace financing": "Finance Solutions",
    "leasing/lease purchase": "Finance Solutions",
    "performance-based incentive": "Rebates",
    "production incentive": "Rebates",
    "net metering": "Rebates",
    "interconnection": "Rebates",
    "industrial recruitment/support": "Investments",
    "industry recruitment/support": "Investments",
    "renewables portfolio standard": "Investments",
    "renewables generation goal": "Investments",
    "energy standards for public buildings": "Investments",
}


class DSIRESpiderExtractor(BaseExtractor):
    """Two-pass DSIRE scraper with deterministic field parsing.

    Pass 1: Playwright loads the FL program list, collects detail URLs.
    Pass 2: Playwright loads each detail page, waits for JS-rendered fields,
            reads `document.body.innerText`, and parses the labeled pairs
            (Incentive Amount, Maximum Incentive, Equipment Requirements,
            Applicable Sectors, Summary, etc.) directly into record dicts.

    Returns RawDocs (text only) for compatibility, but exposes
    `parse_records()` so the pipeline can bypass the LLM for DSIRE.
    """

    def extract(self, source: SourceConfig) -> RawDoc:
        docs = self.extract_many(source)
        if not docs:
            return RawDoc(source.key, source.url, "", self.today_iso())
        return docs[0]

    def extract_many(self, source: SourceConfig) -> list[RawDoc]:
        # Use the cached records from parse_records to avoid double-fetching.
        records = self.parse_records(source)
        # Return one RawDoc per record (text=structured block) for any
        # downstream code that walks raws — kept for backward compat.
        return [
            RawDoc(source.key, r["program_links"], _record_to_text(r), self.today_iso())
            for r in records
        ]

    def parse_records(
        self,
        source: SourceConfig,
        region: Region | None = None,
    ) -> list[dict]:
        """Fetch DSIRE FL programs and return validated record dicts directly.

        If `region` has cities/counties set (e.g. Tampa + Hillsborough), local /
        utility programs not matching those scopes are filtered out — statewide
        and federal programs are always kept since they apply to any FL ZIP.

        Memoized on the SourceConfig instance so extract_many + parse_records
        don't re-scrape.
        """
        cache_key = f"_dsire_cache_{source.key}_{region.slug if region else 'all'}"
        cached = getattr(self, cache_key, None)
        if cached is not None:
            return cached

        from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

        log.info("dsire_spider.start", source=source.key)
        records: list[dict] = []

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            ctx = browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0.0.0 Safari/537.36"
                ),
                ignore_https_errors=True,
            )
            page = ctx.new_page()

            detail_urls = self._get_detail_urls(page, source.url)
            log.info("dsire_spider.urls_found", count=len(detail_urls))

            for i, url in enumerate(detail_urls[:_MAX_PROGRAMS]):
                self._throttle()
                try:
                    try:
                        page.goto(url, wait_until="networkidle", timeout=30_000)
                    except PWTimeout:
                        page.goto(url, wait_until="domcontentloaded", timeout=20_000)
                    # Wait for JS to render the structured fields. The page
                    # always renders "Last Updated" near the program name.
                    try:
                        page.wait_for_function(
                            "() => document.body.innerText.includes('Last Updated')",
                            timeout=10_000,
                        )
                    except Exception:
                        pass
                    page.wait_for_timeout(_WAIT_MS)
                    text = page.evaluate("() => document.body.innerText")
                    rec, drop_reason = _parse_detail_text(text, url, source, region)
                    if rec:
                        records.append(rec)
                        log.info(
                            "dsire_spider.parsed",
                            index=i + 1,
                            program=rec["program_name"][:60],
                            amount=bool(rec.get("incentive_amount")),
                            elig=bool(rec.get("eligibility_criteria")),
                        )
                    elif drop_reason == "out_of_region":
                        log.info("dsire_spider.skipped_region", index=i + 1, url=url)
                    else:
                        log.warning("dsire_spider.parse_failed", url=url)
                except Exception as e:
                    log.warning("dsire_spider.page_failed", url=url, error=str(e))

            browser.close()

        log.info("dsire_spider.done", source=source.key, records=len(records))
        setattr(self, cache_key, records)
        return records

    def _get_detail_urls(self, page, list_url: str) -> list[str]:
        from playwright.sync_api import TimeoutError as PWTimeout
        try:
            page.goto(list_url, wait_until="networkidle", timeout=45_000)
        except PWTimeout:
            page.goto(list_url, wait_until="domcontentloaded", timeout=30_000)
        page.wait_for_timeout(3000)

        links = page.eval_on_selector_all("a", "els => els.map(e => e.href)")
        seen: set[str] = set()
        result: list[str] = []
        for url in links:
            if "/system/program/detail/" in url and url not in seen:
                seen.add(url)
                result.append(url)
        return result


# ──────────────────────────────────────────────────────────────────────────
# Pure parsing helpers (no Playwright dependency, easy to unit-test)
# ──────────────────────────────────────────────────────────────────────────


def _parse_detail_text(
    text: str,
    url: str,
    source: SourceConfig,
    region: Region | None = None,
) -> tuple[dict | None, str | None]:
    """Parse the rendered innerText of a DSIRE detail page into a record dict.

    Returns (record, None) on success, (None, "no_name") if the program name
    can't be located, or (None, "out_of_region") if the program's
    administrator/sector doesn't match the active region.
    """
    lines = [ln.strip() for ln in text.splitlines()]

    program_name = _find_program_name(lines)
    if not program_name:
        return None, "no_name"

    last_updated = _find_last_updated(lines)
    fields = _extract_labeled_fields(lines)
    summary = _extract_summary(text)

    if region is not None and not _matches_region(fields, program_name, region):
        return None, "out_of_region"

    incentive_type = _map_incentive_type(fields.get("Incentive Type", ""))

    # DSIRE's "State" field is a classification ("State", "Federal", "Local",
    # "Utility") — NOT a real US state name. Use the source's default_state
    # (e.g. "Florida" for dsire_fl) since records that pass the region filter
    # apply to that state by definition.
    state = source.default_state or "Florida"

    incentive_amount = _build_incentive_amount(
        fields.get("Incentive Amount"),
        fields.get("Maximum Incentive"),
    )
    eligibility = _build_eligibility(fields)
    description = _build_description(summary, fields, program_name)
    valid_until = _parse_dsire_date(fields.get("Expiration Date"))
    property_type = _map_property_type(fields.get("Applicable Sectors"))

    # Stamp the region's primary city on every surviving record. The region
    # filter already ensured these programs apply to the active region, so
    # `city` represents the city this CSV is scoped to (e.g. Tampa).
    city = (region.cities[0] if region and region.cities else source.default_city)
    rec = {
        "program_name": program_name,
        "state": state,
        "city": city,
        "incentive_type": incentive_type or "Tax Credits",
        "property_type": property_type,
        "description": description,
        "eligibility_criteria": eligibility,
        "incentive_amount": incentive_amount,
        "valid_until": valid_until,
        "updated_at": last_updated or datetime.utcnow().date().isoformat(),
        "review_needed": "No",  # validator will flip to Yes if anything's missing
        "program_links": url,
    }
    return rec, None


def _matches_region(fields: dict[str, str], program_name: str, region: Region) -> bool:
    """Return True if the program is in scope for the given region.

    Rules:
    - State / Federal / Territory programs always pass (they apply everywhere
      in FL, including Tampa).
    - Utility / Local / Municipal programs must reference one of the region's
      cities, counties, or utility providers (case-insensitive substring) in
      either the Administrator field or the program name.
    - If region has no cities/counties/utilities (statewide mode), keep all.
    """
    if not (region.cities or region.counties or region.utility_providers):
        return True

    sector = fields.get("Implementing Sector", "").lower()
    # State and federal programs apply to any FL ZIP including Tampa
    if any(k in sector for k in ("state", "federal", "territory")):
        return True

    administrator = fields.get("Administrator", "")
    haystack = f"{administrator} {program_name}".lower()

    needles: list[str] = []
    needles.extend(c.lower() for c in region.cities)
    needles.extend(c.lower() for c in region.counties)
    needles.extend(u.lower() for u in region.utility_providers)
    # Common abbreviations / aliases
    if "TECO" in region.utility_providers or "Tampa Electric" in region.utility_providers:
        needles.append("teco")
    return any(n and n in haystack for n in needles)


def _find_program_name(lines: list[str]) -> str | None:
    """Program name is the non-empty line immediately preceding 'Last Updated …'."""
    for i, ln in enumerate(lines):
        if ln.startswith("Last Updated"):
            for j in range(i - 1, -1, -1):
                if lines[j]:
                    return lines[j]
    # Fallback: first line after a "Programs" breadcrumb that doesn't look like nav
    return None


def _find_last_updated(lines: list[str]) -> str | None:
    for ln in lines:
        if ln.startswith("Last Updated"):
            # "Last Updated January 2, 2026"
            tail = ln[len("Last Updated"):].strip()
            try:
                dt = datetime.strptime(tail, "%B %d, %Y")
                return dt.date().isoformat()
            except ValueError:
                return None
    return None


def _extract_labeled_fields(lines: list[str]) -> dict[str, str]:
    """Walk the lines, capturing 'Label:' followed by value lines until the
    next labeled line or a section break."""
    out: dict[str, str] = {}
    i = 0
    n = len(lines)
    while i < n:
        ln = lines[i]
        if ln in _LABEL_SET:
            label = ln[:-1]
            value_parts: list[str] = []
            j = i + 1
            while j < n:
                nxt = lines[j]
                if nxt in _LABEL_SET:
                    break
                # Section break — empty followed by section heading like "Summary"
                if nxt in {"Summary", "Authorities", "Recommended Next Steps", "Contact", "Memos"}:
                    break
                if nxt:
                    value_parts.append(nxt)
                else:
                    # blank line ends the value block once we have something
                    if value_parts:
                        break
                j += 1
            out[label] = " ".join(value_parts).strip()
            i = j
        else:
            i += 1
    return out


_SUMMARY_END_MARKERS = ("Authorities", "Recommended Next Steps", "Contact", "Memos", "About DSIRE")


def _extract_summary(text: str) -> str:
    """Capture the free-text Summary block. Falls back to '' if not present."""
    # Find the 'Summary' heading on its own line
    m = re.search(r"\n\s*Summary\s*\n", text)
    if not m:
        return ""
    start = m.end()
    end = len(text)
    for marker in _SUMMARY_END_MARKERS:
        idx = text.find(f"\n{marker}", start)
        if idx != -1:
            end = min(end, idx)
    summary = text[start:end].strip()
    # Collapse internal whitespace
    summary = re.sub(r"\s+", " ", summary)
    return summary


def _map_incentive_type(dsire_type: str) -> str | None:
    if not dsire_type:
        return None
    return _DSIRE_TYPE_TO_SCHEMA.get(dsire_type.strip().lower())


def _build_incentive_amount(amount: str | None, maximum: str | None) -> str | None:
    a = (amount or "").strip()
    m = (maximum or "").strip()
    if a and m:
        return f"{a} (max: {m})"
    return a or m or None


def _build_eligibility(fields: dict[str, str]) -> str | None:
    """Compose eligibility from sectors + equipment + tech requirements."""
    parts: list[str] = []
    sectors = fields.get("Applicable Sectors", "").strip()
    if sectors:
        parts.append(f"Applicable Sectors: {sectors}")
    equip = fields.get("Equipment Requirements", "").strip()
    if equip:
        parts.append(f"Equipment Requirements: {equip}")
    install = fields.get("Installation Requirements", "").strip()
    if install:
        parts.append(f"Installation Requirements: {install}")
    tech_re = fields.get("Eligible Renewable/Other Technologies", "").strip()
    if tech_re:
        parts.append(f"Eligible Technologies: {tech_re}")
    tech_eff = fields.get("Eligible Efficiency Technologies", "").strip()
    if tech_eff:
        parts.append(f"Eligible Efficiency Technologies: {tech_eff}")
    size = fields.get("Eligible System Size", "").strip()
    if size:
        parts.append(f"Eligible System Size: {size}")
    return "; ".join(parts) if parts else None


def _build_description(summary: str, fields: dict[str, str], program_name: str) -> str:
    """Use the Summary text (truncated to ~600 chars at sentence boundary).

    If the summary is missing, synthesize a one-liner from the structured fields.
    """
    if summary:
        if len(summary) <= 600:
            return summary
        cut = summary[:600]
        last_period = cut.rfind(". ")
        if last_period > 200:
            return cut[: last_period + 1]
        return cut.rstrip() + "…"
    # Fallback: synthesize
    pieces = []
    itype = fields.get("Incentive Type", "").strip()
    if itype:
        pieces.append(f"{itype}.")
    admin = fields.get("Administrator", "").strip()
    if admin:
        pieces.append(f"Administered by {admin}.")
    sectors = fields.get("Applicable Sectors", "").strip()
    if sectors:
        pieces.append(f"Available to: {sectors}.")
    return " ".join(pieces) or program_name


def _parse_dsire_date(value: str | None) -> str | None:
    """DSIRE expiration dates render as MM/DD/YYYY."""
    if not value:
        return None
    v = value.strip()
    for fmt in ("%m/%d/%Y", "%Y-%m-%d", "%B %d, %Y"):
        try:
            return datetime.strptime(v, fmt).date().isoformat()
        except ValueError:
            continue
    return None


def _map_property_type(applicable_sectors: str | None) -> str | None:
    """Use the Applicable Sectors string as-is — DSIRE values like
    'Commercial, Industrial, Residential, Agricultural' are already specific
    enough to pass the validator's vague-property check."""
    if not applicable_sectors:
        return None
    return applicable_sectors.strip() or None


def _record_to_text(rec: dict) -> str:
    """Render a record dict back to a labeled text block for any downstream
    code expecting RawDoc.text. Not used by the LLM anymore."""
    lines = [
        f"Program: {rec.get('program_name', '')}",
        f"State: {rec.get('state', '')}",
        f"Incentive Type: {rec.get('incentive_type', '')}",
        f"Property Type: {rec.get('property_type') or ''}",
        f"Incentive Amount: {rec.get('incentive_amount') or ''}",
        f"Eligibility: {rec.get('eligibility_criteria') or ''}",
        f"Valid Until: {rec.get('valid_until') or ''}",
        f"Updated: {rec.get('updated_at', '')}",
        f"URL: {rec.get('program_links', '')}",
        "",
        rec.get("description", ""),
    ]
    return "\n".join(lines)
