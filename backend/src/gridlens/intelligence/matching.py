import hashlib
import re
from typing import Any

_US_STATES = {
    "Alabama",
    "Alaska",
    "Arizona",
    "Arkansas",
    "California",
    "Colorado",
    "Connecticut",
    "Delaware",
    "Florida",
    "Georgia",
    "Hawaii",
    "Idaho",
    "Illinois",
    "Indiana",
    "Iowa",
    "Kansas",
    "Kentucky",
    "Louisiana",
    "Maine",
    "Maryland",
    "Massachusetts",
    "Michigan",
    "Minnesota",
    "Mississippi",
    "Missouri",
    "Montana",
    "Nebraska",
    "Nevada",
    "New Hampshire",
    "New Jersey",
    "New Mexico",
    "New York",
    "North Carolina",
    "North Dakota",
    "Ohio",
    "Oklahoma",
    "Oregon",
    "Pennsylvania",
    "Rhode Island",
    "South Carolina",
    "South Dakota",
    "Tennessee",
    "Texas",
    "Utah",
    "Vermont",
    "Virginia",
    "Washington",
    "West Virginia",
    "Wisconsin",
    "Wyoming",
}


def identity_key(title: str, location: str | None = None) -> str:
    clean = re.sub(r"[^a-z0-9]+", " ", f"{title} {location or ''}".lower()).strip()
    return hashlib.sha256(clean.encode()).hexdigest()


def interpret(record: dict[str, Any]) -> dict[str, str | None] | None:
    from gridlens.domain.qualification import (
        assess_nc_commerce_signal,
        assess_signal,
        nc_commerce_location,
    )

    if record.get("source_id") == "nc-commerce":
        rationale = assess_nc_commerce_signal(record["title"], record.get("abstract"))
        if not rationale:
            return None
        return {
            "name": record["title"],
            "activity_key": "facility-expansion",
            "rationale": rationale,
            "location": nc_commerce_location(record.get("abstract")),
        }
    rationale = assess_signal(record["title"], record.get("abstract"))
    if not rationale:
        return None
    title_parts = [part.strip() for part in record["title"].split(";") if part.strip()]
    name = title_parts[-1] if len(title_parts) > 1 else record["title"]
    location = title_parts[-2] if len(title_parts) > 2 and title_parts[-2] in _US_STATES else None
    return {
        "name": name,
        "activity_key": "mine-development",
        "rationale": rationale,
        "location": location,
    }
