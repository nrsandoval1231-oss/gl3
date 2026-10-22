"""Evidence-bound project geography policy loaded from the versioned source registry."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

REGISTRY_PATH = Path(__file__).resolve().parents[4] / "config" / "sources" / "registry.v1.json"
_REGIONAL_POLICY = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))["regional_policy"]
REGIONAL_POLICY_VERSION = _REGIONAL_POLICY["version"]
REGIONAL_STATES = tuple(_REGIONAL_POLICY["eligible_states"])
REGIONAL_DISABLED_SOURCE_IDS = frozenset(_REGIONAL_POLICY["locked_disabled_sources"])
_STATE_NAMES = {
    "alabama": "AL",
    "alaska": "AK",
    "arizona": "AZ",
    "arkansas": "AR",
    "california": "CA",
    "colorado": "CO",
    "connecticut": "CT",
    "delaware": "DE",
    "florida": "FL",
    "georgia": "GA",
    "hawaii": "HI",
    "idaho": "ID",
    "illinois": "IL",
    "indiana": "IN",
    "iowa": "IA",
    "kansas": "KS",
    "kentucky": "KY",
    "louisiana": "LA",
    "maine": "ME",
    "maryland": "MD",
    "massachusetts": "MA",
    "michigan": "MI",
    "minnesota": "MN",
    "mississippi": "MS",
    "missouri": "MO",
    "montana": "MT",
    "nebraska": "NE",
    "nevada": "NV",
    "new hampshire": "NH",
    "new jersey": "NJ",
    "new mexico": "NM",
    "new york": "NY",
    "north carolina": "NC",
    "north dakota": "ND",
    "ohio": "OH",
    "oklahoma": "OK",
    "oregon": "OR",
    "pennsylvania": "PA",
    "rhode island": "RI",
    "south carolina": "SC",
    "south dakota": "SD",
    "tennessee": "TN",
    "texas": "TX",
    "utah": "UT",
    "vermont": "VT",
    "virginia": "VA",
    "washington": "WA",
    "west virginia": "WV",
    "wisconsin": "WI",
    "wyoming": "WY",
    "district of columbia": "DC",
}
_STATE_CODES = set(_STATE_NAMES.values())
_STATE_NAME_TOKEN = re.compile(
    r"(?:^|[,;/]\s*)(" + "|".join(sorted(_STATE_NAMES, key=len, reverse=True)) + r")"
    r"(?=\s*(?:[,;/]|$|\d{5}))",
    re.I,
)
_STATE_CODE_TOKEN = re.compile(
    r",\s*(" + "|".join(sorted(_STATE_CODES)) + r")"
    r"(?=\s*(?:[,;/]|$|\d{5}))"
)
_POSTAL_STATE_TOKEN = re.compile(
    r"(?:^|[,;/])\s*[A-Za-z][A-Za-z.'-]*(?:\s+[A-Za-z][A-Za-z.'-]*)*\s+"
    r"(" + "|".join(sorted(_STATE_CODES)) + r")\s+\d{5}(?:-\d{4})?"
    r"\s*(?=$|[,;/])"
)
_POSSIBLE_STATE_TOKEN = re.compile(
    r"(?<![A-Za-z0-9])(" + "|".join(sorted(_STATE_CODES)) + r")(?![A-Za-z0-9])"
)
_POSSIBLE_STATE_NAME = re.compile(
    r"(?<![A-Za-z])(" + "|".join(sorted(_STATE_NAMES, key=len, reverse=True)) + r")"
    r"(?=\s*(?:$|[,;/]|\d{5}\b|\b(?:and|or)\b))",
    re.I,
)


@dataclass(frozen=True)
class RegionDecision:
    status: str
    state: str | None
    reason: str
    provenance: dict[str, Any]


def _explicit_states(value: str) -> set[str]:
    states = {
        _STATE_NAMES[match.group(1).casefold()] for match in _STATE_NAME_TOKEN.finditer(value)
    }
    states.update(match.group(1) for match in _STATE_CODE_TOKEN.finditer(value))
    states.update(match.group(1) for match in _POSTAL_STATE_TOKEN.finditer(value))
    return states


def _possible_states(value: str) -> set[str]:
    states = {match.group(1) for match in _POSSIBLE_STATE_TOKEN.finditer(value)}
    states.update(
        _STATE_NAMES[match.group(1).casefold()] for match in _POSSIBLE_STATE_NAME.finditer(value)
    )
    return states


def classify_project_region(
    location: str | None,
    identity_facts: dict[str, Any] | None = None,
    *,
    eligible_states: tuple[str, ...] = REGIONAL_STATES,
    policy_version: str = REGIONAL_POLICY_VERSION,
) -> RegionDecision:
    """Classify explicit physical-site state suffixes; never use HQ or source geography."""
    facts = identity_facts if isinstance(identity_facts, dict) else {}
    fields = {"project.location": location}
    for key in ("site", "site_address", "project_location", "facility_source_address"):
        value = facts.get(key)
        if isinstance(value, str) and value.strip():
            fields[f"identity_facts.{key}"] = value
    states = {
        key: sorted(_explicit_states(value))
        for key, value in fields.items()
        if value and _explicit_states(value)
    }
    unique_states = set().union(*(set(value) for value in states.values())) if states else set()
    # A bare suffix can signal a conflict, but cannot prove a location: prose
    # such as "Everything Is OK" is indistinguishable from a city without
    # a comma or ZIP. Consequently legitimate bare city/state strings hold;
    # uppercase English words matching state codes may also cause a hold.
    possible = {
        key: sorted(_possible_states(value))
        for key, value in fields.items()
        if value and _possible_states(value)
    }
    possible_states = (
        set().union(*(set(value) for value in possible.values())) if possible else set()
    )
    provenance = {
        "policy_version": policy_version,
        "basis": "explicit_project_site_location_state_suffix",
        "fields": states,
        "possible_state_suffixes": possible,
    }
    if unique_states and len(unique_states | possible_states) > 1:
        return RegionDecision("HOLD", None, "conflicting_project_site_states", provenance)
    if not unique_states:
        return RegionDecision("HOLD", None, "project_site_state_unknown", provenance)
    state = next(iter(unique_states))
    if state in eligible_states:
        return RegionDecision("ELIGIBLE", state, "project_site_in_region", provenance)
    return RegionDecision("EXCLUDED", state, "project_site_outside_region", provenance)
