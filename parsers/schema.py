from typing import Literal
from pydantic import BaseModel, Field

INCENTIVE_TYPES = ["Grants", "Rebates", "Finance Solutions", "Tax Credits", "Investments"]
IncentiveType = Literal["Grants", "Rebates", "Finance Solutions", "Tax Credits", "Investments"]

CSV_COLUMN_ORDER = [
    "program_name",
    "state",
    "city",
    "incentive_type",
    "property_type",
    "description",
    "eligibility_criteria",
    "incentive_amount",
    "valid_until",
    "updated_at",
    "review_needed",
    "program_links",
]


class IncentiveRecord(BaseModel):
    program_name: str = Field(..., description="Title of the incentive program")
    state: str = Field(..., description="State name, e.g. 'Florida' or 'USA' for federal")
    city: str | None = Field(None, description="City or county; null if statewide/federal")
    incentive_type: IncentiveType
    property_type: str | None = Field(
        None,
        description="Specific property type — never 'Other', 'Neither', or 'N/A'",
    )
    description: str
    eligibility_criteria: str | None = None
    incentive_amount: str | None = Field(
        None,
        description="Human-readable, e.g. '30% up to $2,000' or 'Up to $10,000'",
    )
    valid_until: str | None = Field(None, description="ISO 8601 YYYY-MM-DD or null")
    updated_at: str = Field(..., description="ISO 8601 YYYY-MM-DD")
    review_needed: Literal["Yes", "No"] = "No"
    program_links: str = Field(..., description="Primary URL for the program")


GEMINI_RESPONSE_SCHEMA = {
    "type": "array",
    "items": {
        "type": "object",
        "properties": {
            "program_name": {"type": "string"},
            "state": {"type": "string"},
            "city": {"type": "string", "nullable": True},
            "incentive_type": {"type": "string", "enum": INCENTIVE_TYPES},
            "property_type": {"type": "string", "nullable": True},
            "description": {"type": "string"},
            "eligibility_criteria": {"type": "string", "nullable": True},
            "incentive_amount": {"type": "string", "nullable": True},
            "valid_until": {"type": "string", "nullable": True},
            "updated_at": {"type": "string"},
            "review_needed": {"type": "string", "enum": ["Yes", "No"]},
            "program_links": {"type": "string"},
        },
        "required": [
            "program_name",
            "state",
            "incentive_type",
            "description",
            "updated_at",
            "review_needed",
            "program_links",
        ],
    },
}
