import json
import os

import structlog

from config.regions import Region
from config.sources import SourceConfig
from extractors.base import RawDoc
from parsers.schema import INCENTIVE_TYPES

log = structlog.get_logger()

SYSTEM_INSTRUCTION = (
    "You are a structured-data extraction specialist for the Dreamline AI "
    "incentive program database. Extract clean-energy, housing, and "
    "hurricane-resilience incentive programs from the provided source content. "
    "Return a JSON array — one object per program — matching the response schema "
    "EXACTLY.\n\n"
    "Hard rules:\n"
    "- Only extract information explicitly stated in the content. Do NOT infer, "
    "guess, or hallucinate amounts, deadlines, or eligibility.\n"
    "- If a field is not mentioned, return null (or set review_needed='Yes').\n"
    "- incentive_type MUST be exactly one of: "
    f"{', '.join(INCENTIVE_TYPES)}.\n"
    "- Map source program types: tax_credit→Tax Credits, grant→Grants, "
    "rebate→Rebates, loan/financing/PACE→Finance Solutions, "
    "fund/large-scale program→Investments.\n"
    "- property_type must be specific (e.g. 'Single-family residential', "
    "'Multifamily', 'Commercial'). Never use 'Other', 'Neither', 'N/A'.\n"
    "- Dates use ISO 8601 (YYYY-MM-DD). If only a year is given (e.g. 'through "
    "2032'), use YYYY-12-31.\n"
    "- Only include ACTIVE programs (even if the current application window is "
    "closed). Skip programs that are permanently ended.\n"
    "- Set review_needed='Yes' when any required field is missing/ambiguous, "
    "amount is unclear, or you are not confident the program is currently active.\n"
    "- program_links is the primary URL the user should visit (application page "
    "preferred; otherwise the source page).\n"
    "- Return [] if the content has no incentive programs."
)


def _build_user_prompt(raw: RawDoc, source: SourceConfig, region: Region) -> str:
    region_summary = (
        f"Active region: state={region.state}"
        + (f", cities={region.cities}" if region.cities else "")
        + (f", counties={region.counties}" if region.counties else "")
        + (f", zip_codes={region.zip_codes}" if region.zip_codes else "")
    )
    return (
        f"Source: {source.name}\n"
        f"Source URL: {raw.url}\n"
        f"Default state: {source.default_state}\n"
        f"Default city: {source.default_city or '(none — use null unless content specifies)'}\n"
        f"Default administrator: {source.default_administrator or '(unknown)'}\n"
        f"Today's date (use for updated_at if source has none): {raw.fetched_at}\n"
        f"{region_summary}\n\n"
        f"--- BEGIN SOURCE CONTENT ---\n{raw.text[:80_000]}\n--- END SOURCE CONTENT ---"
    )


class LLMClient:
    """Groq Llama-3.3-70B (free tier)."""

    def __init__(self, force_provider: str | None = None):
        self._groq = None

    def _groq_client(self):
        if self._groq is None:
            from groq import Groq

            key = os.getenv("GROQ_API_KEY")
            if not key:
                raise RuntimeError("GROQ_API_KEY not set")
            self._groq = Groq(api_key=key)
        return self._groq

    def _call_groq(self, system: str, user: str) -> list[dict]:
        client = self._groq_client()
        groq_addendum = (
            "\n\nOUTPUT FORMAT: Return a JSON object with EXACTLY one top-level key "
            "'programs' whose value is an ARRAY of program records. Example: "
            '{"programs": [{...}, {...}]}. Return {"programs": []} if none found.\n\n'
            "Each record MUST contain these fields (use null for unknowns, never omit):\n"
            "  program_name (string), state (string), city (string|null), "
            "incentive_type (one of: " + ", ".join(INCENTIVE_TYPES) + "), "
            "property_type (string|null — never 'Other'/'Neither'/'N/A'), "
            "description (string), eligibility_criteria (string|null), "
            "incentive_amount (string|null, human-readable like '30% up to $2,000'), "
            "valid_until (YYYY-MM-DD or null), updated_at (YYYY-MM-DD), "
            "review_needed ('Yes' or 'No'), program_links (string URL).\n"
            "Do NOT wrap string fields in arrays or nested objects."
        )
        resp = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": system + groq_addendum},
                {"role": "user", "content": user},
            ],
            response_format={"type": "json_object"},
            temperature=0.1,
        )
        payload = json.loads(resp.choices[0].message.content)
        if isinstance(payload, list):
            return payload
        for key in ("programs", "records", "items", "data", "results"):
            if key in payload and isinstance(payload[key], list):
                return payload[key]
        # Single-record dict fallback
        if isinstance(payload, dict) and "program_name" in payload:
            return [payload]
        return []

    def parse(self, system: str, user: str) -> list[dict]:
        return self._call_groq(system, user)


def parse_doc(
    raw: RawDoc,
    source: SourceConfig,
    region: Region,
    client: LLMClient,
) -> list[dict]:
    if not raw.text or len(raw.text.strip()) < 100:
        log.warning("llm.skip_empty_doc", source=source.key)
        return []

    user_prompt = _build_user_prompt(raw, source, region)
    log.info("llm.parse", source=source.key, chars=len(raw.text))
    try:
        records = client.parse(SYSTEM_INSTRUCTION, user_prompt)
    except Exception as e:
        log.error("llm.parse_failed", source=source.key, error=str(e))
        return []

    log.info("llm.parse_done", source=source.key, n_records=len(records))
    return records
