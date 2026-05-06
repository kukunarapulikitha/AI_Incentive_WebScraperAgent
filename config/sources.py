import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

VALID_EXTRACTOR_TYPES = {"html", "pdf", "api", "playwright", "apify", "dsire_spider"}
VALID_PRIORITIES = {"P0", "P1", "P2"}
_CUSTOM_SOURCES_PATH = Path(__file__).resolve().parent / "custom_sources.json"


@dataclass
class SourceConfig:
    key: str
    name: str
    url: str
    extractor_type: str  # "html" | "pdf" | "api" | "playwright" | "apify"
    priority: str  # "P0" | "P1" | "P2"
    applicable_states: list[str]  # ["ALL"] for federal/national; ["FL"] for Florida-only
    default_state: str  # what to stamp on records if LLM doesn't infer
    default_city: str | None = None
    default_administrator: str | None = None
    notes: str = ""
    api_params: dict = field(default_factory=dict)


SOURCES: dict[str, SourceConfig] = {
    # ── P0 ───────────────────────────────────────────────────────────────────
    "dsire_fl": SourceConfig(
        key="dsire_fl",
        name="DSIRE Florida",
        url="https://programs.dsireusa.org/system/program?state=FL",
        extractor_type="dsire_spider",
        priority="P0",
        applicable_states=["FL"],
        default_state="Florida",
        default_administrator="DSIRE / NCSU",
        notes="Two-pass spider: Playwright gets list → follows each detail URL → one LLM call per program.",
    ),
    "rewiring_ira": SourceConfig(
        key="rewiring_ira",
        name="Rewiring America IRA Programs",
        url="https://www.rewiringamerica.org/policy/inflation-reduction-act",
        extractor_type="html",
        priority="P0",
        applicable_states=["ALL"],
        default_state="USA",
        default_administrator="Federal / IRS",
        notes="IRA policy page — static list of all federal IRA consumer programs and credits.",
    ),
    "irs_energy_credits": SourceConfig(
        key="irs_energy_credits",
        name="IRS Home Energy Tax Credits",
        url="https://www.irs.gov/credits-deductions/home-energy-tax-credits",
        extractor_type="html",
        priority="P0",
        applicable_states=["ALL"],
        default_state="USA",
        default_administrator="IRS",
        notes="25C + 25D federal credits. Static HTML, no JS needed.",
    ),
    "teco_rebates": SourceConfig(
        key="teco_rebates",
        name="TECO Residential Rebates",
        url="https://www.tampaelectric.com/home/save-energy/rebates/",
        extractor_type="playwright",
        priority="P0",
        applicable_states=["FL"],
        default_state="Florida",
        default_city="Tampa",
        default_administrator="Tampa Electric (TECO)",
        notes="Blocks plain requests. Playwright renders page. TECO service territory rebates.",
    ),
    "doe_energy_saver": SourceConfig(
        key="doe_energy_saver",
        name="DOE Energy Saver — Tax Credits & Rebates",
        url="https://www.energy.gov/energysaver/federal-tax-credits-energy-efficiency",
        extractor_type="html",
        priority="P0",
        applicable_states=["ALL"],
        default_state="USA",
        default_administrator="U.S. Department of Energy",
        notes="DOE summary of all federal energy efficiency tax credits and rebates.",
    ),
    # ── P1 ───────────────────────────────────────────────────────────────────
    "my_safe_fl_home": SourceConfig(
        key="my_safe_fl_home",
        name="My Safe Florida Home",
        url="https://mysafeflhome.com/",
        extractor_type="html",
        priority="P1",
        applicable_states=["FL"],
        default_state="Florida",
        default_administrator="Florida Department of Financial Services",
        notes="Hurricane mitigation grant — up to $10K. Statewide.",
    ),
    "irs_energy_credits_detail": SourceConfig(
        key="irs_energy_credits_detail",
        name="IRS Energy Efficient Home Improvement Credit (25C)",
        url="https://www.irs.gov/credits-deductions/energy-efficient-home-improvement-credit",
        extractor_type="html",
        priority="P1",
        applicable_states=["ALL"],
        default_state="USA",
        default_administrator="IRS",
        notes="Detailed 25C page — windows, doors, HVAC, insulation, audits.",
    ),
    "duke_fl_rebates": SourceConfig(
        key="duke_fl_rebates",
        name="Duke Energy Florida Rebates",
        url="https://www.duke-energy.com/home/products/rebates",
        extractor_type="playwright",
        priority="P1",
        applicable_states=["FL"],
        default_state="Florida",
        default_administrator="Duke Energy Florida",
        notes="Blocks plain requests. Playwright needed.",
    ),
    "fl_housing": SourceConfig(
        key="fl_housing",
        name="Florida Housing Finance Corporation",
        url="https://floridahousing.org/homebuyers-homeowners/homeowners",
        extractor_type="playwright",
        priority="P1",
        applicable_states=["FL"],
        default_state="Florida",
        default_administrator="Florida Housing Finance Corporation",
        notes="SHIP, HOME, DPA programs. Homeowners overview page.",
    ),
    "hillsborough_housing": SourceConfig(
        key="hillsborough_housing",
        name="Hillsborough County Affordable Housing",
        url="https://hcfl.gov/housing",
        extractor_type="playwright",
        priority="P1",
        applicable_states=["FL"],
        default_state="Florida",
        default_city="Tampa",
        default_administrator="Hillsborough County",
        notes="SHIP, CDBG, county rehab programs. hcfl.gov is the official domain.",
    ),
    "fl_solar_tax_exemptions": SourceConfig(
        key="fl_solar_tax_exemptions",
        name="Florida Solar Sales Tax & Property Tax Exemptions",
        url="https://www.energy.gov/eere/solar/homeowner-s-guide-going-solar",
        extractor_type="html",
        priority="P1",
        applicable_states=["FL"],
        default_state="Florida",
        default_administrator="State of Florida / Department of Revenue",
        notes="DOE homeowner guide covers FL property tax and sales tax solar exemptions.",
    ),
    "fl_energy_programs": SourceConfig(
        key="fl_energy_programs",
        name="Florida Energy Programs (DEO)",
        url="https://www.floridajobs.org/community-planning-and-development/assistance-for-governments-and-organizations/energy",
        extractor_type="playwright",
        priority="P1",
        applicable_states=["FL"],
        default_state="Florida",
        default_administrator="Florida Department of Economic Opportunity",
        notes="State energy efficiency and weatherization programs through DEO.",
    ),
    # ── P2 ───────────────────────────────────────────────────────────────────
    "city_tampa_dev": SourceConfig(
        key="city_tampa_dev",
        name="City of Tampa Community Development",
        url="https://www.tampa.gov/community-development",
        extractor_type="playwright",
        priority="P2",
        applicable_states=["FL"],
        default_state="Florida",
        default_city="Tampa",
        default_administrator="City of Tampa",
        notes="Local rehabilitation and housing programs.",
    ),
    "fema_mitigation": SourceConfig(
        key="fema_mitigation",
        name="FEMA Hazard Mitigation Grants",
        url="https://www.fema.gov/grants/mitigation",
        extractor_type="html",
        priority="P2",
        applicable_states=["ALL"],
        default_state="USA",
        default_administrator="FEMA",
        notes="HMGP, BRIC programs. Federal hazard mitigation grants.",
    ),
    "ygrene_pace": SourceConfig(
        key="ygrene_pace",
        name="Ygrene PACE Financing",
        url="https://ygrene.com/what-we-offer/",
        extractor_type="playwright",
        priority="P2",
        applicable_states=["FL"],
        default_state="Florida",
        default_administrator="Ygrene Energy Fund",
        notes="PACE zero-down financing for solar, HVAC, roofing, windows.",
    ),
    "pace_florida": SourceConfig(
        key="pace_florida",
        name="Florida PACE Funding Agency (FPFA)",
        url="https://floridapace.org/",
        extractor_type="html",
        priority="P2",
        applicable_states=["FL"],
        default_state="Florida",
        default_administrator="Florida PACE Funding Agency",
        notes="PACE financing overview for Florida homeowners.",
    ),
    "doe_weatherization": SourceConfig(
        key="doe_weatherization",
        name="DOE Weatherization Assistance Program",
        url="https://www.energy.gov/scep/wap/weatherization-assistance-program",
        extractor_type="html",
        priority="P2",
        applicable_states=["ALL"],
        default_state="USA",
        default_administrator="U.S. Department of Energy",
        notes="Federal WAP grant for low-income households.",
    ),
}


def _load_custom_sources() -> dict[str, SourceConfig]:
    """Load user-defined sources from config/custom_sources.json (if present).

    The file is a JSON array of source objects with the same fields as
    SourceConfig. Hand-editable; also written by `main.py add-source`.
    """
    if not _CUSTOM_SOURCES_PATH.exists():
        return {}
    try:
        raw = json.loads(_CUSTOM_SOURCES_PATH.read_text() or "[]")
    except json.JSONDecodeError as e:
        raise ValueError(
            f"custom_sources.json is not valid JSON: {e}. Fix or delete the file."
        ) from e
    out: dict[str, SourceConfig] = {}
    for item in raw:
        cfg = SourceConfig(
            key=item["key"],
            name=item["name"],
            url=item["url"],
            extractor_type=item["extractor_type"],
            priority=item.get("priority", "P1"),
            applicable_states=item.get("applicable_states", ["ALL"]),
            default_state=item.get("default_state", "USA"),
            default_city=item.get("default_city"),
            default_administrator=item.get("default_administrator"),
            notes=item.get("notes", ""),
        )
        out[cfg.key] = cfg
    return out


def _read_custom_sources_raw() -> list[dict]:
    if not _CUSTOM_SOURCES_PATH.exists():
        return []
    return json.loads(_CUSTOM_SOURCES_PATH.read_text() or "[]")


def _write_custom_sources_raw(items: list[dict]) -> None:
    _CUSTOM_SOURCES_PATH.write_text(json.dumps(items, indent=2) + "\n")


def add_custom_source(cfg: SourceConfig, *, overwrite: bool = False) -> None:
    """Append a SourceConfig to custom_sources.json. Raises if the key clashes
    with a built-in source or an existing custom source (unless overwrite=True).

    Mutates the in-memory `SOURCES` dict so the new source is usable in the
    same process — useful for `main.py add-source && main.py --sources <key>`.
    """
    if cfg.key in BUILTIN_SOURCES:
        raise ValueError(
            f"key {cfg.key!r} clashes with a built-in source — pick a different key."
        )
    if cfg.extractor_type not in VALID_EXTRACTOR_TYPES:
        raise ValueError(
            f"extractor_type {cfg.extractor_type!r} not in {sorted(VALID_EXTRACTOR_TYPES)}"
        )
    if cfg.priority not in VALID_PRIORITIES:
        raise ValueError(f"priority {cfg.priority!r} not in {sorted(VALID_PRIORITIES)}")

    items = _read_custom_sources_raw()
    existing_idx = next((i for i, x in enumerate(items) if x.get("key") == cfg.key), None)
    if existing_idx is not None and not overwrite:
        raise ValueError(
            f"custom source {cfg.key!r} already exists — pass overwrite=True to replace."
        )

    payload = asdict(cfg)
    if existing_idx is not None:
        items[existing_idx] = payload
    else:
        items.append(payload)
    _write_custom_sources_raw(items)
    SOURCES[cfg.key] = cfg


def remove_custom_source(key: str) -> bool:
    """Remove a custom source by key. Returns True if removed, False if not found."""
    items = _read_custom_sources_raw()
    new_items = [x for x in items if x.get("key") != key]
    if len(new_items) == len(items):
        return False
    _write_custom_sources_raw(new_items)
    SOURCES.pop(key, None)
    return True


def select_sources(
    region_state: str,
    only_keys: list[str] | None = None,
) -> list[SourceConfig]:
    """Return sources whose applicable_states include the active region's state (or ALL)."""
    if only_keys:
        return [SOURCES[k] for k in only_keys if k in SOURCES]
    return [
        s for s in SOURCES.values()
        if "ALL" in s.applicable_states or region_state.upper() in s.applicable_states
    ]


# Snapshot the built-in sources before merging custom ones so add_custom_source
# can detect collisions with the curated registry.
BUILTIN_SOURCES: dict[str, SourceConfig] = dict(SOURCES)
SOURCES.update(_load_custom_sources())
