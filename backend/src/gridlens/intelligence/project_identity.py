import re
from dataclasses import dataclass

_ADDRESS = re.compile(
    r"\b\d{1,6}\s+[A-Za-z0-9.'#-]+(?:\s+[A-Za-z0-9.'#-]+){0,5}\s+"
    r"(?:st|street|rd|road|ave|avenue|blvd|boulevard|dr|drive|hwy|highway|way|lane|ln|"
    r"court|ct|route|rt)\b(?:\s*,\s*[A-Za-z .'-]+\s*,\s*(?:[A-Z]{2}|[A-Za-z ]+))?",
    re.IGNORECASE,
)
_LABELED_SITE = re.compile(
    r"\b(?:site\s+address|project\s+site|site|address)\s*(?:is|:)?\s*"
    r"(" + _ADDRESS.pattern + r")",
    re.IGNORECASE,
)
_STATE_NAMES = {
    "alabama",
    "alaska",
    "arizona",
    "arkansas",
    "california",
    "colorado",
    "connecticut",
    "delaware",
    "florida",
    "georgia",
    "hawaii",
    "idaho",
    "illinois",
    "indiana",
    "iowa",
    "kansas",
    "kentucky",
    "louisiana",
    "maine",
    "maryland",
    "massachusetts",
    "michigan",
    "minnesota",
    "mississippi",
    "missouri",
    "montana",
    "nebraska",
    "nevada",
    "new hampshire",
    "new jersey",
    "new mexico",
    "new york",
    "north carolina",
    "north dakota",
    "ohio",
    "oklahoma",
    "oregon",
    "pennsylvania",
    "rhode island",
    "south carolina",
    "south dakota",
    "tennessee",
    "texas",
    "utah",
    "vermont",
    "virginia",
    "washington",
    "west virginia",
    "wisconsin",
    "wyoming",
}
_STATE_CODES = {
    "AL": "alabama",
    "AK": "alaska",
    "AZ": "arizona",
    "AR": "arkansas",
    "CA": "california",
    "CO": "colorado",
    "CT": "connecticut",
    "DE": "delaware",
    "FL": "florida",
    "GA": "georgia",
    "HI": "hawaii",
    "ID": "idaho",
    "IL": "illinois",
    "IN": "indiana",
    "IA": "iowa",
    "KS": "kansas",
    "KY": "kentucky",
    "LA": "louisiana",
    "ME": "maine",
    "MD": "maryland",
    "MA": "massachusetts",
    "MI": "michigan",
    "MN": "minnesota",
    "MS": "mississippi",
    "MO": "missouri",
    "MT": "montana",
    "NE": "nebraska",
    "NV": "nevada",
    "NH": "new hampshire",
    "NJ": "new jersey",
    "NM": "new mexico",
    "NY": "new york",
    "NC": "north carolina",
    "ND": "north dakota",
    "OH": "ohio",
    "OK": "oklahoma",
    "OR": "oregon",
    "PA": "pennsylvania",
    "RI": "rhode island",
    "SC": "south carolina",
    "SD": "south dakota",
    "TN": "tennessee",
    "TX": "texas",
    "UT": "utah",
    "VT": "vermont",
    "VA": "virginia",
    "WA": "washington",
    "WV": "west virginia",
    "WI": "wisconsin",
    "WY": "wyoming",
}
_STREET_SUFFIXES = {
    "st": "st", "street": "st", "rd": "rd", "road": "rd",
    "ave": "ave", "avenue": "ave", "blvd": "blvd", "boulevard": "blvd",
    "dr": "dr", "drive": "dr", "hwy": "hwy", "highway": "hwy",
    "way": "way", "lane": "ln", "ln": "ln", "court": "ct",
    "ct": "ct", "route": "rt", "rt": "rt",
}


@dataclass(frozen=True)
class MatchDecision:
    decision: str
    reason: str
    matched_facts: tuple[str, ...]


def normalized_identity(value: str | None) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (value or "").casefold()).strip()


def canonical_site_claim(value: str | None) -> str:
    """Compare full site claims, folding only unambiguous street and state forms."""
    raw = (value or "").strip()
    tokens = normalized_identity(raw).split()
    street_component = raw.split(",", 1)[0]
    street = _ADDRESS.match(street_component)
    if street is not None:
        street_words = normalized_identity(street.group()).split()
        suffix_count = sum(word in _STREET_SUFFIXES for word in street_words[1:])
        # A comma bounds the street. Without one, a second suffix-like word
        # could actually be the city (for example, Court or Drive).
        if street_words and ("," in raw or suffix_count == 1):
            street_words[-1] = _STREET_SUFFIXES.get(street_words[-1], street_words[-1])
            tokens = street_words + normalized_identity(raw[street.end():]).split()
    state_end = len(tokens)
    if (
        len(tokens) >= 3
        and re.fullmatch(r"\d{5}", tokens[-2])
        and re.fullmatch(r"\d{4}", tokens[-1])
    ):
        state_end -= 2
    elif tokens and re.fullmatch(r"\d{5}", tokens[-1]):
        state_end -= 1
    if state_end >= 2 and tokens[state_end - 1].upper() in _STATE_CODES:
        tokens[state_end - 1 : state_end] = _STATE_CODES[tokens[state_end - 1].upper()].split()
    return " ".join(tokens)


def physical_site(value: str | None) -> bool:
    clean = normalized_identity(value)
    return bool(
        re.search(r"\b\d{1,6}\b", clean)
        and re.search(
            r"\b(st|street|rd|road|ave|avenue|blvd|boulevard|dr|drive|ln|lane|hwy|highway|parcel|lot)\b",
            clean,
        )
    )


def labeled_site(text: str | None) -> str | None:
    """Return only an explicitly labeled site/address claim for identity matching."""
    sites = labeled_sites(text)
    return sites[0] if len(sites) == 1 else None


def labeled_sites(text: str | None) -> tuple[str, ...]:
    """Return distinct explicitly labeled addresses in source order."""
    sites: list[str] = []
    seen: set[str] = set()
    for match in _LABELED_SITE.finditer(text or ""):
        site = " ".join(match.group(1).split()).rstrip(".,;")
        key = normalized_identity(site)
        if key and key not in seen:
            seen.add(key)
            sites.append(site)
    return tuple(sites)


def same_physical_site(left: str | None, right: str | None) -> bool:
    if not physical_site(left) or not physical_site(right):
        return False
    left_match, right_match = _ADDRESS.search(left or ""), _ADDRESS.search(right or "")
    return bool(
        left_match
        and right_match
        and normalized_identity(left_match.group()) == normalized_identity(right_match.group())
    )


def conflicting_geography(left: str | None, right: str | None) -> bool:
    """Detect explicit city/state disagreement while allowing address vs city/state detail."""

    def parts(value: str | None) -> tuple[str | None, str | None]:
        segments = [part.strip() for part in (value or "").split(",") if part.strip()]
        if not segments:
            return None, None
        last = segments[-1].upper()
        state = _STATE_CODES.get(last) or (
            last.casefold() if last.casefold() in _STATE_NAMES else None
        )
        city = normalized_identity(segments[-2]) if state and len(segments) > 1 else None
        return city, state

    left_city, left_state = parts(left)
    right_city, right_state = parts(right)
    return bool(
        (left_state and right_state and left_state != right_state)
        or (left_city and right_city and left_city != right_city)
    )


def stable_asset_identity(record: dict[str, object], source_id: str) -> tuple[str, str] | None:
    permit = record.get("permit")
    nested_project = permit.get("project") if isinstance(permit, dict) else None
    candidates = (
        ("api_number", record.get("api_number")),
        ("well_id", record.get("well_id")),
        ("parcel_id", record.get("parcel_id")),
        ("asset_id", record.get("asset_id")),
        ("permit_project", nested_project),
    )
    for field, raw in candidates:
        if not isinstance(raw, str) or normalized_identity(raw) in {
            "",
            "unknown",
            "na",
            "n a",
            "none",
            "null",
            "0",
        }:
            continue
        value = raw.strip().casefold()
        if field == "api_number":
            digits = re.sub(r"\D", "", value)
            if len(digits) not in {10, 12, 14} or not digits.strip("0"):
                continue
            return "us_well_api", digits
        return f"{source_id}:{field}", value
    return None


def phase_normalized_facility_scope(record: dict[str, object]) -> str | None:
    """Normalize only an explicit numbered phase; all remaining source text must match."""
    permit = record.get("permit")
    if not isinstance(permit, dict):
        return None
    description = permit.get("description")
    address = permit.get("address")
    if (
        not isinstance(description, str)
        or not isinstance(address, str)
        or not physical_site(address)
        or not re.search(r"\bphase\s+\d+\s*:", description, re.I)
    ):
        return None
    return normalized_identity(re.sub(r"\bphase\s+\d+\s*:\s*", "phase ", description, flags=re.I))


def decide_project_match(
    *,
    same_source_id: bool = False,
    same_address: bool = False,
    same_project_name: bool = False,
    same_asset_identity: bool = False,
    same_authoritative_scope: bool = False,
    same_owner: bool = False,
    explicit_relationship: bool = False,
    conflicting_geography: bool = False,
    conflicting_asset_type: bool = False,
) -> MatchDecision:
    """Conservative identity gate. Company/owner alone can never merge projects."""
    facts = tuple(
        name
        for name, yes in (
            ("stable source id", same_source_id),
            ("physical address", same_address),
            ("project name/alias", same_project_name),
            ("asset identity", same_asset_identity),
            ("phase-normalized authoritative permit scope", same_authoritative_scope),
            ("owner/developer", same_owner),
            ("explicit source relationship", explicit_relationship),
        )
        if yes
    )
    strong = same_source_id or same_asset_identity or explicit_relationship
    corroborated_site = same_address and (same_project_name or same_authoritative_scope)
    if (strong or corroborated_site) and not conflicting_geography and not conflicting_asset_type:
        return MatchDecision("matched", f"Identity supported by {', '.join(facts)}.", facts)
    if conflicting_geography:
        return MatchDecision(
            "separate", "Conflicting geographic evidence; records remain separate.", facts
        )
    if conflicting_asset_type:
        return MatchDecision("separate", "Conflicting asset type; records remain separate.", facts)
    return MatchDecision(
        "separate", "Insufficient identity evidence; ambiguous observations remain separate.", facts
    )
