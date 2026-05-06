import re
from datetime import date

import structlog
from pydantic import ValidationError

from parsers.schema import INCENTIVE_TYPES, IncentiveRecord

log = structlog.get_logger()

_VAGUE_PROPERTY_TYPES = {"other", "neither", "n/a", "na", "unknown", ""}
_NULL_LIKE = {"", "null", "none", "n/a", "na", "unknown", "tbd", "not specified"}
_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_YEAR_ONLY = re.compile(r"^(\d{4})$")

_INCENTIVE_TYPE_ALIASES = {
    "grant": "Grants",
    "grants": "Grants",
    "rebate": "Rebates",
    "rebates": "Rebates",
    "tax credit": "Tax Credits",
    "tax credits": "Tax Credits",
    "credit": "Tax Credits",
    "credits": "Tax Credits",
    "loan": "Finance Solutions",
    "loans": "Finance Solutions",
    "financing": "Finance Solutions",
    "finance": "Finance Solutions",
    "finance solution": "Finance Solutions",
    "finance solutions": "Finance Solutions",
    "pace": "Finance Solutions",
    "investment": "Investments",
    "investments": "Investments",
    "fund": "Investments",
}


def _stringify(value) -> str | None:
    """Coerce list/dict/None into a readable string or None."""
    if value is None:
        return None
    if isinstance(value, str):
        s = value.strip()
        return None if s.lower() in _NULL_LIKE else s
    if isinstance(value, list):
        parts = [_stringify(v) for v in value]
        parts = [p for p in parts if p]
        return "; ".join(parts) if parts else None
    if isinstance(value, dict):
        parts = [f"{k}: {v}" for k, v in value.items() if v not in (None, "")]
        return "; ".join(parts) if parts else None
    return str(value)


def _normalize_date(value) -> str | None:
    """Return ISO YYYY-MM-DD or None if unparseable."""
    s = _stringify(value)
    if not s:
        return None
    if _ISO_DATE.match(s):
        return s
    m = _YEAR_ONLY.match(s)
    if m:
        return f"{m.group(1)}-12-31"
    return None


def _normalize_incentive_type(value) -> str | None:
    s = _stringify(value)
    if not s:
        return None
    if s in INCENTIVE_TYPES:
        return s
    return _INCENTIVE_TYPE_ALIASES.get(s.lower())


def _coerce(record: dict) -> dict:
    """Best-effort cleanup before pydantic validation."""
    cleaned: dict = {}

    cleaned["program_name"] = _stringify(record.get("program_name")) or ""
    cleaned["state"] = _stringify(record.get("state")) or "USA"
    cleaned["city"] = _stringify(record.get("city"))

    inc_type = _normalize_incentive_type(record.get("incentive_type"))
    cleaned["incentive_type"] = inc_type or "Grants"  # placeholder; flagged below
    cleaned["_incentive_type_was_invalid"] = inc_type is None

    cleaned["property_type"] = _stringify(record.get("property_type"))
    cleaned["description"] = _stringify(record.get("description")) or ""
    cleaned["eligibility_criteria"] = _stringify(record.get("eligibility_criteria"))
    cleaned["incentive_amount"] = _stringify(record.get("incentive_amount"))

    cleaned["valid_until"] = _normalize_date(record.get("valid_until"))
    cleaned["updated_at"] = _normalize_date(record.get("updated_at")) or date.today().isoformat()

    rn = _stringify(record.get("review_needed"))
    cleaned["review_needed"] = "Yes" if (rn and rn.lower() == "yes") else "No"

    cleaned["program_links"] = _stringify(record.get("program_links")) or ""

    return cleaned


def _needs_review(rec: IncentiveRecord, type_was_invalid: bool) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    if type_was_invalid:
        reasons.append("incentive_type not in controlled vocab")
    if rec.property_type and rec.property_type.strip().lower() in _VAGUE_PROPERTY_TYPES:
        reasons.append("vague property_type")
    if rec.valid_until and not _ISO_DATE.match(rec.valid_until):
        reasons.append("valid_until not ISO 8601")
    if not _ISO_DATE.match(rec.updated_at):
        reasons.append("updated_at not ISO 8601")
    if not rec.description or len(rec.description.strip()) < 10:
        reasons.append("description too short")
    if not rec.eligibility_criteria:
        reasons.append("missing eligibility_criteria")
    if not rec.incentive_amount:
        reasons.append("missing incentive_amount")
    return (len(reasons) > 0, reasons)


def validate(record_dict: dict) -> IncentiveRecord | None:
    """Coerce + validate one record. Returns None if unsalvageable."""
    cleaned = _coerce(record_dict)
    type_was_invalid = cleaned.pop("_incentive_type_was_invalid", False)

    if not cleaned["program_name"].strip() or not cleaned["program_links"].startswith(("http://", "https://")):
        log.warning(
            "validate.unsalvageable",
            program=cleaned.get("program_name"),
            link=cleaned.get("program_links"),
        )
        return None

    try:
        rec = IncentiveRecord(**cleaned)
    except ValidationError as e:
        log.warning("validate.pydantic_failed", error=str(e), data=cleaned)
        return None

    needs, reasons = _needs_review(rec, type_was_invalid)
    if needs:
        rec.review_needed = "Yes"
        log.info("validate.flagged", program=rec.program_name, reasons=reasons)

    return rec
