"""Conservative qualification of retained RSS title and summary text.

This is a bounded rule parser, not general entity resolution. It only promotes
claims explicit in supplied title/summary; ambiguous relationships stay rejected.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Any

EVALUATOR_VERSION = "rss-project-v10"
_STATES = (
    "Alabama|Alaska|Arizona|Arkansas|California|Colorado|Connecticut|Delaware|Florida|Georgia|"
    "Hawaii|Idaho|Illinois|Indiana|Iowa|Kansas|Kentucky|Louisiana|Maine|Maryland|"
    "Massachusetts|Michigan|Minnesota|Mississippi|Missouri|Montana|Nebraska|Nevada|"
    "New Hampshire|New Jersey|New Mexico|New York|North Carolina|North Dakota|Ohio|"
    "Oklahoma|Oregon|Pennsylvania|Rhode Island|South Carolina|South Dakota|Tennessee|"
    "Texas|Utah|Vermont|Virginia|Washington|West Virginia|Wisconsin|Wyoming"
)
_STATE_RE = re.compile(rf"\b({_STATES})\b", re.I)
_CITIES = {
    "West Memphis": "Arkansas",
    "Houston": "Texas",
    "Dallas": "Texas",
    "Fort Worth": "Texas",
    "Austin": "Texas",
    "San Antonio": "Texas",
    "Pine Bluff": "Arkansas",
    "Little Rock": "Arkansas",
    "Huntsville": "Alabama",
    "Birmingham": "Alabama",
    "Phoenix": "Arizona",
    "Denver": "Colorado",
    "Atlanta": "Georgia",
    "Chicago": "Illinois",
    "Indianapolis": "Indiana",
    "Detroit": "Michigan",
    "Columbus": "Ohio",
    "Oklahoma City": "Oklahoma",
    "Nashville": "Tennessee",
    "Seattle": "Washington",
    "Los Angeles": "California",
    "San Francisco": "California",
    "New York": "New York",
    "Philadelphia": "Pennsylvania",
    "Monrovia": "Indiana",
}
_STATE_ABBREVIATIONS = {
    "AL": "Alabama",
    "AK": "Alaska",
    "AZ": "Arizona",
    "AR": "Arkansas",
    "CA": "California",
    "CO": "Colorado",
    "CT": "Connecticut",
    "DE": "Delaware",
    "FL": "Florida",
    "GA": "Georgia",
    "HI": "Hawaii",
    "ID": "Idaho",
    "IL": "Illinois",
    "IN": "Indiana",
    "IA": "Iowa",
    "KS": "Kansas",
    "KY": "Kentucky",
    "LA": "Louisiana",
    "ME": "Maine",
    "MD": "Maryland",
    "MA": "Massachusetts",
    "MI": "Michigan",
    "MN": "Minnesota",
    "MS": "Mississippi",
    "MO": "Missouri",
    "MT": "Montana",
    "NE": "Nebraska",
    "NV": "Nevada",
    "NH": "New Hampshire",
    "NJ": "New Jersey",
    "NM": "New Mexico",
    "NY": "New York",
    "NC": "North Carolina",
    "ND": "North Dakota",
    "OH": "Ohio",
    "OK": "Oklahoma",
    "OR": "Oregon",
    "PA": "Pennsylvania",
    "RI": "Rhode Island",
    "SC": "South Carolina",
    "SD": "South Dakota",
    "TN": "Tennessee",
    "TX": "Texas",
    "UT": "Utah",
    "VT": "Vermont",
    "VA": "Virginia",
    "WA": "Washington",
    "WV": "West Virginia",
    "WI": "Wisconsin",
    "WY": "Wyoming",
}
_OUTSIDE_US = re.compile(
    r"(?<!New )\b(Mexico|Japan|South Korea|Korea|Canada|United Kingdom|UK|Germany|India|"
    r"China|Taiwan|"
    r"France|Australia|Singapore|Malaysia|Thailand|Vietnam|Indonesia|Poland|Israel)\b",
    re.I,
)
_FOREIGN_SITE_LOCATION = re.compile(
    r"\b(?:in|at|near|around)\s+"
    r"(?:(?:[A-Z][\w.'-]*(?:\s+[A-Z][\w.'-]*){0,2}),\s*)?"
    r"(?:Mexico|Japan|South Korea|Korea|Canada|United Kingdom|UK|Germany|India|China|Taiwan|"
    r"France|Australia|Singapore|Malaysia|Thailand|Vietnam|Indonesia|Poland|Israel)\b",
    re.I,
)
_FACILITY = re.compile(
    r"\b(?:AI )?(?:data cent(?:er|re)|campus|manufacturing (?:campus|plant|facility)|"
    r"manufacturing|plant|factory|facility|water reclamation plant|water project|"
    r"industrial (?:site|project)|processing facility|greenhouse|mine|hospital|"
    r"medical center|shipyard|smelter|hotel|"
    r"chip fabs?|semiconductor fabs?|fabs?|expansion|"
    r"arena|stadium|offices)\b",
    re.I,
)
_ACTION = re.compile(
    r"\b(?:breaks? ground|groundbreak(?:ing)?|begins? construction|will be built|"
    r"starts? on(?: the)? (?:\$[\d,.]+(?:m|b|bn|million|billion)?\s*)?"
    r"(?:concrete )?(?:deck|(?:facility )?expansion)|"
    r"begins? (?:the )?(?:concrete )?deck|"
    r"sells?\b[^.]{0,100}\b(?:smelter|site|land|parcel)\b|"
    r"(?:smelter|site|land|parcel)\s+(?:is |was )?sold\b|"
    r"files? for\s+(?:a\s+)?(?:second|new|additional|\d+(?:st|nd|rd|th))\s+building|"
    r"(?:will\s+)?fund\s+(?:renewable energy and )?grid upgrades|"
    r"(?:to\s+)?close\s+in\s+\d{4}\s+for\s+(?:multiyear|multi-year|major|substantial)\s+"
    r"(?:facade\s+)?restoration|"
    r"files? to (?:build|construct)|plans? to (?:build|construct|"
    r"expand|establish|open)|to (?:build|construct|expand|establish|open)|will (?:build|"
    r"construct|expand|establish|open)|(?:build|construct|expand|establish|open)(?:s|ed|ing)?)\b",
    re.I,
)
# Pre-construction data-center milestones: a concrete site, financing, a power
# contract for a planned site, or conversion of an existing site. Only admitted in a
# span that also names a data center, and never for company deals or exploratory
# interest (those remain speculative or non-facility reporting).
_EARLY_DC_ACTION = re.compile(
    r"\b(?:application (?:is )?filed for\s+(?:a\s+)?"
    r"(?:[\d.,]+\s+(?:million\s+)?(?:sq\.?\s*ft\.?\s+)?)?"
    r"(?:new\s+)?(?:AI\s+)?data cent(?:er|re)(?:\s+campus)?|"
    r"approves?\b.{0,160}\b(?:solar|storage|transmission|power)\b.{0,100}\b"
    r"(?:data cent(?:er|re)|campus)|"
    r"acquires?\s+(?:\d[\d,]*\s+acres|land|(?:a |the )?(?:[a-z]+\s+)?site)\b|"
    r"secures?\s+\$[\d.,]+\s*(?:m|bn|b|million|billion)\s+(?:in\s+)?"
    r"(?:debt\s+|equity\s+|project\s+)?financing\s+for\b|"
    r"power (?:deal|agreement|contract)\b[^.]{0,60}\bfor (?:a |its |the )?"
    r"(?:planned|proposed|new|future) (?:AI )?data cent(?:er|re)|"
    r"(?:pivot|convert)(?:s|ed|ing)?\s+(?:[\w$.-]+\s+){0,4}into\b)",
    re.I,
)
_DATA_CENTER = re.compile(r"\bdata cent(?:er|re)\b", re.I)
_NEGATED = re.compile(
    r"\b(?:cancel(?:s|ed|led|lation)?|scrap(?:s|ped)?|withdraw(?:s|n|al)?|rescind(?:s|ed)?|"
    r"abandon(?:s|ed|ment)?|halt(?:s|ed)?|not proceeding|no longer proceeding|shelved|denied)\b",
    re.I,
)
_SPECULATIVE = re.compile(
    r"\b(?:could|may|might|reportedly|rumou?red|speculat(?:e|ion)|forecast|opinion|editorial|"
    r"eyed|explores?|exploring)\b",
    re.I,
)
_NON_EVENT = re.compile(
    r"\b(?:policy|regulator|licen[cs]|recall|sales|retailer|acquisition|merger|lawsuit|"
    r"interconnection study|complaint|investment pledge|aggregate|nationwide|portfolio)\b",
    re.I,
)
_GENERATION = re.compile(
    r"\b(?:generation|generator|nameplate|campus capacity|site capacity|plant output|"
    r"mixed technology)\b",
    re.I,
)
_MW_DEMAND = re.compile(
    r"\b(?:requires?|needs?|will consume|will use|expects? to draw|load (?:of|requires?))\s+"
    r"(?:about |approximately |at least |up to )?(?:[1-9]\d*(?:\.\d+)?|0\.\d+)\s*"
    r"(?:MW|megawatts?)\b",
    re.I,
)
_MW_VALUE = re.compile(
    r"\b(?:(?:approximately|about|up to|at least)\s+)?(?:[1-9]\d*(?:\.\d+)?|0\.\d+)\s*"
    r"(?:MW|megawatts?)\b",
    re.I,
)
_SUPPLY_RESOLVED = re.compile(
    r"\b(?:adequate|secured|available)\s+(?:power|electric(?:ity|al)? supply|grid connection|"
    r"utility service)\b|"
    r"\b(?:power|electric(?:ity|al)? supply|grid connection|utility service)\b.{0,80}\b"
    r"(?:is|remains|has)\s+(?:adequate|secured|available)\b|"
    r"\b(?:has|have)\s+adequate\s+supply\b|\bnow\s+(?:adequate|secured|available)\b|"
    r"\bno longer\s+(?:delayed|insufficient|unavailable)\b",
    re.I,
)
_ACTIVITY = re.compile(
    r"\b(?:construction|commissioning|manufacturing|production|operations)\b", re.I
)
_CLAIM_NEGATED = re.compile(
    r"\b(?:does not|do not|not|never)\s+(?:require|need|delayed?|late|insufficient|unavailable)\b",
    re.I,
)
_GENERIC_ACTORS = {
    "a company",
    "a developer",
    "a consortium",
    "a contractor",
    "investor",
    "investors",
    "developer",
    "developers",
    "official",
    "officials",
    "construction",
}


@dataclass(frozen=True)
class NewsAssessment:
    decision: str
    tier: str | None
    reason: str
    subject: str | None
    action: str | None
    location: str | None
    demand_quote: str | None
    demand_mw: str | None
    supply_quote: str | None
    missing_facts: list[str]

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class _PowerClause:
    kind: str
    activity: str
    quote: str
    mw: str | None = None


def _sentences(text: str) -> list[str]:
    return [part.strip() for part in re.split(r"(?<=[.!?])\s+", text) if part.strip()]


def _site_location(text: str) -> str | None:
    """Find a US place grammatically attached to the facility event, never an actor HQ."""
    text = re.sub(rf"\b(?:{_STATES})-based\b", "", text, flags=re.I)
    facility_match = _FACILITY.search(text)

    def has_non_site_party_clause_without_site_reset(end: int) -> bool:
        if facility_match is None or end <= facility_match.end():
            return False
        intervening = text[facility_match.end() : end]
        customer = re.search(
            r"\b(?:customers?|clients?|buyers?|partners?|contractors?|suppliers?|investors?)\b",
            intervening,
            re.I,
        )
        if customer is None:
            return False
        return (
            re.search(
                r"\b(?:site|facility|plant|data cent(?:er|re)|campus|project)\b",
                intervening[customer.end() :],
                re.I,
            )
            is None
        )

    def grounded_place_precedes_facility(place_match: re.Match[str]) -> bool:
        if facility_match is None or place_match.end() > facility_match.start():
            return False
        between = text[place_match.end() : facility_match.start()]
        if re.search(
            r"\b(?:developers?|customers?|clients?|buyers?|partners?|contractors?|suppliers?|investors?)\b",
            between,
            re.I,
        ):
            return False
        return bool(
            not between.strip()
            or re.fullmatch(r"\s+(?:[A-Za-z0-9]+(?:-[A-Za-z0-9]+)?\s+)?", between)
            or re.match(r"\s*(?:'|\u2019)s\b", between)
        )

    named_states = list(_STATE_RE.finditer(text))
    state_coreference = bool(
        facility_match
        and re.search(
            r"^\s*(?:in|within)\s+the\s+state\b",
            text[facility_match.end() :],
            re.I,
        )
        and len(named_states) == 1
        and named_states[0].end() <= facility_match.start()
    )

    # Prefer an explicit state attached to the project. Skip states attached
    # to customer clauses unless a later site/facility phrase resets the relation.
    for state in named_states:
        before = text[max(0, state.start() - 10) : state.start()]
        city_before = text[max(0, state.start() - 40) : state.start()]
        direct = bool(
            re.search(r"\b(?:in|at|near)\s*$", before, re.I)
            or re.search(
                r"\b(?:in|at|near)\s+[A-Z][\w.'-]*(?:\s+[A-Z][\w.'-]*){0,2},\s*$",
                city_before,
            )
        )
        if not direct or has_non_site_party_clause_without_site_reset(state.start()):
            continue

        for city, city_state in sorted(
            _CITIES.items(), key=lambda item: len(item[0]), reverse=True
        ):
            city_match = re.search(rf"\b{re.escape(city)}\b", text, re.I)
            if (
                city_match is None
                or city_match.start() > state.start()
                or city_state.casefold() != state.group(1).casefold()
            ):
                continue
            project_linked = False
            if grounded_place_precedes_facility(city_match):
                project_linked = True
            elif facility_match and city_match.start() >= facility_match.end():
                prefix = text[facility_match.end() : city_match.start()]
                project_linked = bool(re.search(r"\b(?:in|at|near)\s+$", prefix, re.I))
                if has_non_site_party_clause_without_site_reset(city_match.start()):
                    project_linked = False
            elif not facility_match:
                project_linked = True
            if project_linked:
                return (
                    city
                    if city.casefold() == state.group(1).casefold()
                    else f"{city}, {state.group(1)}"
                )

        city_state_match = re.search(
            r"\b(?:in|at|near)\s+([A-Z][\w.'-]*(?:\s+[A-Z][\w.'-]*){0,2}),\s*$",
            city_before,
        )
        if city_state_match:
            return f"{city_state_match.group(1)}, {state.group(1)}"
        return state.group(1)

    # A project-linked city can be stated before its facility name or directly
    # after a location preposition, before considering less specific fallbacks.
    for city, state_name in sorted(_CITIES.items(), key=lambda item: len(item[0]), reverse=True):
        city_match = re.search(rf"\b{re.escape(city)}\b", text, re.I)
        if city_match is None:
            continue
        before = text[max(0, city_match.start() - 10) : city_match.start()]
        after_facility = bool(
            facility_match
            and city_match.start() >= facility_match.end()
            and re.search(
                r"\b(?:in|at|near)\s+$", text[facility_match.end() : city_match.start()], re.I
            )
            and not has_non_site_party_clause_without_site_reset(city_match.start())
        )
        before_facility = grounded_place_precedes_facility(city_match)
        if re.search(
            r"\b(?:in|at|near)\s*$", before, re.I
        ) and not has_non_site_party_clause_without_site_reset(city_match.start()):
            return city if city.casefold() == state_name.casefold() else f"{city}, {state_name}"
        if after_facility or before_facility:
            return city if city.casefold() == state_name.casefold() else f"{city}, {state_name}"

    # Keep a state directly modifying the facility ("Georgia factory"), but
    # do not infer the site from a nearby developer or customer state.
    if facility_match:
        for state in _STATE_RE.finditer(text):
            if state.end() <= facility_match.start() and grounded_place_precedes_facility(state):
                return state.group(1)
    # A unique named state can ground an explicit coreference attached
    # immediately to the facility, after direct city and state sites win.
    if state_coreference and len(named_states) == 1:
        return named_states[0].group(1)
    embedded = re.search(
        rf"\b([A-Z][\w.'-]*(?:\s+[A-Z][\w.'-]*){{0,2}})\s+"
        rf"(?:data cent(?:er|re)|campus|plant|facility|site|hotel|shipyard),\s*({_STATES})\b",
        text,
    )
    if embedded:
        return f"{embedded.group(1)}, {embedded.group(2)}"
    if re.search(r"\bNYC(?:[’']s)?\b", text) and re.search(r"\bhotel\b", text, re.I):
        return "New York, New York"
    abbreviation = re.search(r"\b(?:in|at|near)\s+([A-Z]{2})\b|,\s*([A-Z]{2})\b", text)
    if abbreviation:
        code = abbreviation.group(1) or abbreviation.group(2)
        if code in _STATE_ABBREVIATIONS:
            return _STATE_ABBREVIATIONS[code]
    return None


def _early_dc_action(span: str) -> re.Match[str] | None:
    return _EARLY_DC_ACTION.search(span) if _DATA_CENTER.search(span) else None


def _event_span(title: str, summary: str) -> str | None:
    for span in [title, *_sentences(summary)]:
        if _FACILITY.search(span) and _ACTION.search(span):
            return span
    for span in [title, *_sentences(summary)]:
        if _early_dc_action(span):
            return span
    return None


def _event_location(title: str, summary: str, event: str | None) -> str | None:
    """Do not infer a plant location from a separate company/background sentence."""
    # A project-linked foreign location is authoritative even if the same event
    # contains a US state token (for example, a Georgia factory near Monterrey).
    # Requiring the location phrase to follow the facility avoids treating an
    # actor's foreign headquarters as the project's site.
    for span in (event, title):
        if span:
            facility_match = _FACILITY.search(span)
            foreign_location = _FOREIGN_SITE_LOCATION.search(span)
            site_modifier = (
                span[facility_match.end() : foreign_location.start()]
                if facility_match and foreign_location
                else ""
            )
            domestic_site = (
                _site_location(span[: foreign_location.start()])
                if facility_match and foreign_location
                else None
            )
            partner_context = bool(
                domestic_site
                and facility_match
                and foreign_location
                and re.search(
                    r"\b(?:with|among|and)\b[^.;]{0,100}\b"
                    r"(?:partners?|contractors?|suppliers?|investors?)\b",
                    span[facility_match.end() : foreign_location.start()],
                    re.I,
                )
            )
            if (
                facility_match
                and foreign_location
                and foreign_location.start() >= facility_match.end()
                and not re.search(
                    r"[.;]|\b(?:headquarters?|HQ|headquartered|based)\b", site_modifier, re.I
                )
                and not partner_context
            ):
                return None
    for span in (event, title):
        if span:
            location = _site_location(span)
            if location:
                return location
    if event:
        # A named state plus a physical build/area-addition clause grounds an
        # expansion title even when the article omits the facility's proper name.
        expansion_proof = re.search(
            rf"\b({_STATES})\s+build\b[^.]*\badd\b[^.]*\b"
            r"(?:square feet|sq\.?\s*ft\.?|sf)\b",
            summary,
            re.I,
        )
        if expansion_proof and re.search(r"\bexpansion\b", event, re.I):
            return expansion_proof.group(1)
        facility_match = _FACILITY.search(event)
        if facility_match is None:
            return None
        facility_words = set(re.findall(r"[a-z]+", facility_match.group(0).lower()))
        for sentence in _sentences(summary):
            # A demonstrative reference to the same facility binds a short abstract
            # sentence to the headline, without borrowing a company headquarters.
            reference = re.match(
                rf"^(?:the|its|this)\s+{re.escape(facility_match.group(0))}\b",
                sentence,
                re.I,
            )
            if reference and not _OUTSIDE_US.search(sentence):
                location = _site_location(sentence)
                if location:
                    return location
            if _ACTION.search(sentence) and facility_words.intersection(
                re.findall(r"[a-z]+", sentence.lower())
            ):
                if not _OUTSIDE_US.search(sentence):
                    location = _site_location(sentence)
                    if location:
                        return location
    return None


def _subject(title: str, summary: str, event: str) -> str | None:
    application_site = re.search(
        r"\bapplication filed for\s+(?P<site>[\d,.]+\s+(?:million\s+)?"
        r"(?:sq\.?\s*ft\.?\s+)?(?:AI\s+)?data cent(?:er|re) campus)\b",
        title,
        re.I,
    )
    if application_site:
        return " ".join(application_site.group("site").split())
    expansion = re.match(
        r"^([A-Z][\w&.'’-]*(?:\s+[A-Z][\w&.'’-]*){0,3}),\s+.*\bstart on\b.*\bexpansion\b",
        title,
    )
    if expansion:
        return f"{expansion.group(1)} expansion"
    named = re.search(
        r"\b([A-Z][\w&.'’-]*(?:\s+[A-Z0-9][\w&.'’-]*){0,3}(?:\s+[a-z]+){0,2}\s+"
        r"(?:AI\s+)?(?:data cent(?:er|re)|campus|chip fab|fab|plant|factory|facility|"
        r"project|site|arena|stadium))\b",
        event,
    )
    if named:
        return named.group(1).strip()
    if event != title:
        named = re.search(
            r"\b([A-Z][\w&.'’-]*(?:\s+[A-Z0-9][\w&.'’-]*){0,3}\s+(?:data cent(?:er|re)|campus|"
            r"plant|factory|facility|project|fab))\b",
            title,
        )
        if named:
            return named.group(1).strip()
    milestone_actor = re.match(
        r"^\s*([A-Z][\w&.'’-]*(?:\s+[A-Z][\w&.'’-]*){0,3})\s+"
        r"(?:sells?|files? for|expands? partnership)\b",
        title,
    )
    if milestone_actor:
        return milestone_actor.group(1).strip()
    hotel = re.search(r"\b([A-Z][\w&.'’-]*(?:\s+[A-Z][\w&.'’-]*){0,3}\s+Hotel)\b", title)
    if hotel:
        return hotel.group(1)
    company = re.search(
        r"^\s*([A-Z][\w&.'’-]*(?:\s+[A-Z][\w&.'’-]*){0,3}"
        r"(?:\s+(?:joint venture|JV))?)\s+"
        r"(?:files? to (?:build|construct)|breaks? ground|groundbreak|"
        r"begins? (?:construction|(?:the )?(?:concrete )?deck)|"
        r"starts? on|build(?:s|ing)?|construct(?:s|ing)?|to |will |plans? to )",
        title,
    )
    if company:
        return company.group(1).strip()
    for sentence in _sentences(summary):
        named = re.search(
            r"\b([A-Z][\w&.'’-]*(?:\s+[A-Z0-9][\w&.'’-]*){0,3}(?:\s+[a-z]+){0,2}\s+"
            r"(?:Water Reclamation Plant|data cent(?:er|re)|campus|plant|factory|facility|"
            r"project|site|arena|stadium))\b",
            sentence,
        )
        if named:
            return named.group(1).strip()
    return None


def _missing() -> list[str]:
    return ["activity-specific power requirement", "supply suitability", "start window", "duration"]


def _identifiable_subject(subject: str) -> bool:
    return subject.strip().lower() not in _GENERIC_ACTORS


def _claim_has_site_and_activity(claim: str, subject: str) -> bool:
    phrase = " ".join(re.findall(r"[A-Za-z0-9]+", subject))
    has_exact_site = bool(
        phrase and re.search(rf"(?<![A-Za-z0-9]){re.escape(phrase)}(?![A-Za-z0-9])", claim, re.I)
    )
    return bool(has_exact_site and _claim_activity(claim, phrase))


def _claim_activity(claim: str, subject_phrase: str) -> set[str]:
    """Read phases after removing the exact site name (which can include 'manufacturing')."""
    without_site = re.sub(
        rf"(?<![A-Za-z0-9]){re.escape(subject_phrase)}(?![A-Za-z0-9])", "", claim, flags=re.I
    )
    return {phase.lower() for phase in _ACTIVITY.findall(without_site)}


def _is_complete_adverse_supply_clause(claim: str, subject: str) -> bool:
    """Accept only one complete affirmative supply clause, never an adverse substring."""
    subject_phrase = " ".join(re.findall(r"[A-Za-z0-9]+", subject))
    activities = "construction|commissioning|manufacturing|production|operations"
    return bool(
        subject_phrase
        and re.fullmatch(
            rf"\s*(?:power\s+supply|electric(?:ity|al)?\s+supply|grid\s+connection|"
            rf"utility\s+service)\s+for\s+"
            rf"{re.escape(subject_phrase)}\s+(?:{activities})\s+(?:is|remains)\s+"
            rf"(?:delayed|insufficient|unavailable)\s*[.!?]?\s*",
            claim,
            re.I,
        )
    )


def validated_demand_mw(subject: str, demand_quote: str, power_activity: str) -> str | None:
    """Return the one explicit positive MW requirement for the bound site/activity."""
    candidate = _complete_demand_clause(subject, demand_quote)
    return candidate[1] if candidate and candidate[0] == power_activity else None


def _complete_demand_clause(subject: str, clause: str) -> tuple[str, str] | None:
    """Parse one exact-site, exact-activity, complete affirmative MW requirement."""
    subject_phrase = " ".join(re.findall(r"[A-Za-z0-9]+", subject))
    if not subject_phrase:
        return None
    activities = "construction|commissioning|manufacturing|production|operations"
    match = re.fullmatch(
        rf"\s*{re.escape(subject_phrase)}\s+(?P<activity>{activities})\s+"
        rf"(?:requires?|needs?|will\s+consume|will\s+use|expects?\s+to\s+draw)\s+"
        rf"(?P<mw>(?:about|approximately|at\s+least|up\s+to)\s+)?"
        rf"(?P<number>[1-9]\d*(?:\.\d+)?|0\.\d+)\s*(?P<unit>MW|megawatts?)\s*[.!?]?\s*",
        clause,
        re.I,
    )
    if match is None or _CLAIM_NEGATED.search(clause) or _SPECULATIVE.search(clause):
        return None
    qualifier = match.group("mw") or ""
    return match.group("activity").lower(), " ".join(
        f"{qualifier}{match.group('number')} {match.group('unit')}".split()
    )


def _claim_clauses(span: str) -> list[str]:
    return [
        clause.strip()
        for clause in re.split(r"(?:[.;!?]\s+|,\s*(?:but|while)\s+)", span)
        if clause.strip()
    ]


def _power_clause(subject: str, clause: str) -> _PowerClause | None:
    """Parse exactly one retained evidence unit for one named site and activity."""
    demand = _complete_demand_clause(subject, clause)
    if demand:
        return _PowerClause("demand", demand[0], clause, demand[1])
    phrase = " ".join(re.findall(r"[A-Za-z0-9]+", subject))
    activities = "construction|commissioning|manufacturing|production|operations"
    if not phrase:
        return None
    supply_prefix = (
        r"(?:power\s+supply|electric(?:ity|al)?\s+supply|grid\s+connection|utility\s+service)"
        rf"\s+for\s+{re.escape(phrase)}\s+(?P<activity>{activities})\s+"
    )
    adverse = re.fullmatch(
        supply_prefix + r"(?:is|remains)\s+(?:delayed|insufficient|unavailable)\s*[.!?]?\s*",
        clause,
        re.I,
    )
    if adverse:
        return _PowerClause("adverse", adverse.group("activity").lower(), clause)
    resolved = (
        re.fullmatch(
            rf"{re.escape(phrase)}\s+(?P<activity>{activities})\s+(?:now\s+)?has\s+adequate\s+supply\s*[.!?]?\s*",
            clause,
            re.I,
        )
        or re.fullmatch(
            supply_prefix + r"(?:is|remains|has)\s+(?:adequate|secured|available)\s*[.!?]?\s*",
            clause,
            re.I,
        )
        or re.fullmatch(
            supply_prefix + r"is\s+now\s+(?:adequate|secured|available)\s*[.!?]?\s*",
            clause,
            re.I,
        )
    )
    if resolved:
        return _PowerClause("resolved", resolved.group("activity").lower(), clause)
    return None


def _action_activity(action: str) -> str | None:
    """Map every action admitted by the event grammar to its supported phase."""
    normalized = action.strip()
    if _EARLY_DC_ACTION.fullmatch(normalized) is not None:
        # Site, financing and power-contract milestones precede construction power.
        return "construction"
    if re.search(r"\b(?:sells?|sold|fund)\b", normalized, re.I):
        return None
    if re.search(r"\b(?:restoration|files? for|deck|start on .*expansion)\b", normalized, re.I):
        return "construction"
    if _ACTION.fullmatch(normalized) is None:
        return None
    if re.search(r"\bopen", normalized, re.I):
        return "operations"
    return "construction"


def _event_action(event: str) -> re.Match[str] | None:
    # A project-specific grid commitment takes precedence over a corporate
    # partnership expansion elsewhere in the same headline.
    grid = re.search(r"\b(?:will\s+)?fund\s+(?:renewable energy and )?grid upgrades\b", event, re.I)
    return grid or _ACTION.search(event)


def _event_activity(event: str) -> str | None:
    action = _event_action(event)
    return _action_activity(action.group(0)) if action else None


def _has_same_activity_supply_resolution(
    title: str, summary: str, subject: str, candidate_activity: str | None, event: str
) -> bool:
    """Find a confirmed resolution for the candidate phase.

    A validated demand-plus-adverse-supply pair establishes its own power phase.
    Only when no such candidate exists may the physical event phase provide a
    conservative fallback for closure.
    """
    activity = candidate_activity or _event_activity(event)
    if activity is None:
        return False
    for span in [title, *_sentences(summary)]:
        for clause in _claim_clauses(span):
            parsed = _power_clause(subject, clause)
            if parsed and parsed.kind == "resolved" and parsed.activity == activity:
                return True
    return False


def prospect_power_activity(subject: str, demand_quote: str, supply_quote: str) -> str | None:
    """Return the one validated shared phase for two explicit Prospect claims.

    The exact site phrase must occur in both quotes. Site-name words are removed
    before phase extraction, preventing a name such as ``manufacturing plant``
    from being treated as a manufacturing activity.
    """
    subject_phrase = " ".join(re.findall(r"[A-Za-z0-9]+", subject))
    if (
        demand_quote == supply_quote
        or not _claim_has_site_and_activity(demand_quote, subject)
        or not _claim_has_site_and_activity(supply_quote, subject)
        or _CLAIM_NEGATED.search(demand_quote)
        or _CLAIM_NEGATED.search(supply_quote)
        or _SPECULATIVE.search(demand_quote)
        or _SPECULATIVE.search(supply_quote)
        or not _is_complete_adverse_supply_clause(supply_quote, subject)
        or _SUPPLY_RESOLVED.search(supply_quote)
    ):
        return None
    shared = _claim_activity(demand_quote, subject_phrase).intersection(
        _claim_activity(supply_quote, subject_phrase)
    )
    return next(iter(shared)) if len(shared) == 1 else None


def _prospect_claims(title: str, summary: str, subject: str) -> tuple[str | None, str | None]:
    demands: list[tuple[str, str, str]] = []
    supplies: list[tuple[str, str]] = []
    resolutions: set[str] = set()
    for span in [title, *_sentences(summary)]:
        if _OUTSIDE_US.search(span):
            continue
        if _CLAIM_NEGATED.search(span) or _SPECULATIVE.search(span):
            continue
        for clause in _claim_clauses(span):
            parsed = _power_clause(subject, clause)
            if parsed is None and re.fullmatch(
                r"\s*now\s+(?:adequate|secured|available)\s*[.!?]?\s*", clause, re.I
            ):
                return None, None
            if parsed is None:
                continue
            if parsed.kind == "resolved":
                resolutions.add(parsed.activity)
                continue
            if parsed.kind == "demand" and parsed.mw:
                demands.append((parsed.quote, parsed.activity, parsed.mw))
            if parsed.kind == "adverse":
                supplies.append((parsed.quote, parsed.activity))
    if len(supplies) != 1:
        return None, None
    supply, activity = supplies[0]
    if activity in resolutions:
        return None, None
    matching_demands = [demand for demand in demands if demand[1] == activity]
    if len(matching_demands) != 1:
        return None, None
    demand: str = matching_demands[0][0]
    if prospect_power_activity(subject, demand, supply) != activity:
        return None, None
    return demand, supply


def _candidate_power_activity(title: str, summary: str, subject: str) -> str | None:
    """Return the one bound demand/supply phase before considering resolution."""
    demands: list[tuple[str, str]] = []
    supplies: list[tuple[str, str]] = []
    for span in [title, *_sentences(summary)]:
        if _OUTSIDE_US.search(span) or _CLAIM_NEGATED.search(span) or _SPECULATIVE.search(span):
            continue
        for clause in _claim_clauses(span):
            parsed = _power_clause(subject, clause)
            if parsed is None:
                continue
            if parsed.kind == "demand" and parsed.mw:
                demands.append((parsed.quote, parsed.activity))
            elif parsed.kind == "adverse":
                supplies.append((parsed.quote, parsed.activity))
    if len(supplies) != 1:
        return None
    supply, activity = supplies[0]
    matching_demands = [demand for demand in demands if demand[1] == activity]
    if len(matching_demands) != 1:
        return None
    return (
        activity
        if prospect_power_activity(subject, matching_demands[0][0], supply) == activity
        else None
    )


def signal_power_activity(action: str | None) -> str | None:
    """Map only a validated retained physical action to a supported activity."""
    return _action_activity(action) if action else None


def _rejected(reason: str, location: str | None = None) -> NewsAssessment:
    return NewsAssessment(
        "rejected", None, reason, None, None, location, None, None, None, _missing()
    )


def assess_news(title: str, summary: str | None) -> NewsAssessment:
    """Assess retained RSS text; ambiguous text stays in the inbox as ``rejected``."""
    title = " ".join(title.split())
    summary = " ".join((summary or "").split())[:500]
    text = f"{title} {summary}".strip()
    event = _event_span(title, summary)
    location = _event_location(title, summary, event)
    if _NEGATED.search(text):
        return _rejected(
            "The retained text includes a canceled, denied, withdrawn, or halted activity.",
            location,
        )
    if re.search(r"\b(?:recruits?|recruiting|hires?|hiring|job openings?)\b", title, re.I):
        return _rejected("The retained headline is hiring news rather than a project event.")
    if _SPECULATIVE.search(title):
        return _rejected(
            "The retained text is speculative rather than a confirmed physical project event.",
            location,
        )
    if event and re.search(
        r"\b(?:in|at|near)\s+(?:Canada|Mexico|Japan|Germany|India|China|Australia|"
        r"Singapore|Malaysia|France|United Kingdom)\b",
        event,
        re.I,
    ):
        return _rejected("The physical event is explicitly located outside the US.")
    if (_OUTSIDE_US.search(title) or (event and _OUTSIDE_US.search(event))) and not location:
        outside = _OUTSIDE_US.search(title) or _OUTSIDE_US.search(event or "")
        if outside is not None:
            return _rejected(
                f"The identified project event is outside the US Signal scope ({outside.group(1)})."
            )
    if not event:
        if _NON_EVENT.search(text):
            return _rejected(
                "The retained text is policy, commercial, generation, or other "
                "non-facility reporting."
            )
        return _rejected(
            "The retained text does not establish a physical facility and a concrete "
            "project action."
        )
    if not location:
        return _rejected("A US project location is not stated with the physical facility event.")
    early_match = None if _event_action(event) else _early_dc_action(event)
    if early_match is not None:
        subject = _subject(title, summary, event)
        if subject is None:
            # The deal's actor names the planned site; never a counterparty.
            actor = re.match(r"\s*([A-Z][\w&.'’-]*(?:\s+[A-Z][\w&.'’-]*){0,3})\s+[a-z]", title)
            subject = f"{actor.group(1).strip()} data center" if actor else None
    else:
        subject = _subject(title, summary, event)
    if not subject or not _identifiable_subject(subject):
        return _rejected(
            "No identifiable company, project, or named site is retained with the physical event.",
            location,
        )
    candidate_activity = _candidate_power_activity(title, summary, subject)
    if _has_same_activity_supply_resolution(title, summary, subject, candidate_activity, event):
        return _rejected(
            "The retained text supports adequate supply for the same site and project activity.",
            location,
        )
    demand_quote, supply_quote = _prospect_claims(title, summary, subject)
    action_match = _event_action(event)
    if early_match is not None:
        action_match = early_match
    facility_match = _FACILITY.search(event)
    if action_match is None or facility_match is None:
        return _rejected(
            "The retained text does not establish a qualifying physical project action."
        )
    action = action_match.group(0)
    facility = facility_match.group(0).lower()
    if demand_quote and supply_quote:
        power_activity = prospect_power_activity(subject, demand_quote, supply_quote)
        demand_mw = (
            validated_demand_mw(subject, demand_quote, power_activity)
            if power_activity is not None
            else None
        )
        if demand_mw is None:
            demand_quote, supply_quote = None, None
        else:
            return NewsAssessment(
                "accepted",
                "Prospect",
                "Separate explicit retained claims bind an activity-specific MW requirement "
                "and unsuitable supply to the same named site and activity.",
                subject,
                action,
                location,
                demand_quote,
                demand_mw,
                supply_quote,
                ["required MW range", "start window", "duration", "remaining supply gap"],
            )
    location_basis = ""
    if ", " in location:
        city, state = location.split(", ", maxsplit=1)
        location_basis = (
            f" The retained city is {city}; {state} is a bounded city-to-state mapping."
        )
    return NewsAssessment(
        "accepted",
        "Signal",
        f"The retained text reports {action} for {subject}, a {facility} event in "
        f"{location}; power facts require investigation.{location_basis}",
        subject,
        action,
        location,
        None,
        None,
        None,
        _missing(),
    )
