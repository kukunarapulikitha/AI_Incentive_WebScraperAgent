from dataclasses import dataclass, field


@dataclass
class Region:
    slug: str
    state: str
    cities: list[str] = field(default_factory=list)
    counties: list[str] = field(default_factory=list)
    zip_codes: list[str] = field(default_factory=list)
    utility_providers: list[str] = field(default_factory=list)


REGIONS: dict[str, Region] = {
    "tampa_hillsborough": Region(
        slug="tampa_hillsborough",
        state="FL",
        cities=["Tampa"],
        counties=["Hillsborough"],
        utility_providers=["TECO", "Tampa Electric"],
    ),
    "tampa_bay_msa": Region(
        slug="tampa_bay_msa",
        state="FL",
        cities=["Tampa", "St. Petersburg", "Clearwater", "Bradenton", "New Port Richey"],
        counties=["Hillsborough", "Pinellas", "Pasco", "Manatee", "Hernando"],
        utility_providers=["TECO", "Duke Energy", "Tampa Electric"],
    ),
    "florida_statewide": Region(
        slug="florida_statewide",
        state="FL",
        cities=[],
        counties=[],
        utility_providers=["TECO", "Duke Energy", "FPL"],
    ),
}


def build_region(
    region_key: str | None,
    state: str | None,
    zip_codes: list[str] | None,
) -> Region:
    """Resolve a Region from CLI flags. CLI overrides preset fields if both given."""
    if region_key and region_key in REGIONS:
        base = REGIONS[region_key]
    elif state:
        base = Region(slug=f"custom_{state.lower()}", state=state.upper())
    else:
        base = REGIONS["tampa_hillsborough"]

    return Region(
        slug=base.slug,
        state=(state or base.state).upper(),
        cities=base.cities,
        counties=base.counties,
        zip_codes=zip_codes or base.zip_codes,
        utility_providers=base.utility_providers,
    )
