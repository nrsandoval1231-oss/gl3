"""Explicit project research claims; no qualification, lifecycle inference or I/O."""

from __future__ import annotations

import re
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

VERSION = "project-research-claims-v4"
FIELDS = (
    "phase",
    "permanent_service",
    "supply_adequacy",
    "temporary_supply",
    "activity_load_mw",
    "activity_start",
    "facility_scale_mw",
    "facility_demand_mw",
    "voltage",
    "fuel_availability",
    "load_profile",
    "procurement_status",
    "utility_obstacle",
)
_PHASES = (
    ("cancelled", r"(?:project|development|facility) (?:is |was |has been )?cancel(?:led|ed)"),
    ("completed", r"(?:project|development|facility) (?:is |was |has been )?completed"),
    (
        "paused",
        r"(?:project|construction|development) (?:is |was |has been )?(?:paused|suspended|on hold)",
    ),
    ("commissioning", r"commissioning (?:is (?:currently )?underway|has (?:begun|started)|began)"),
    (
        "electrical_buildout",
        r"electrical (?:rough[ -]in|buildout|installation) "
        r"(?:is (?:currently )?underway|has begun)",
    ),
    (
        "production_infrastructure_under_construction",
        r"production infrastructure (?:is (?:currently )?under construction|is being built)",
    ),
    ("drilling_completed", r"drilling (?:is complete|has been completed|was completed)"),
    (
        "production_started",
        r"production (?:has (?:begun|started)|is (?:currently )?underway|began)",
    ),
    (
        "construction_active",
        r"(?:construction|site work) (?:is (?:currently )?underway|has (?:begun|started)|began)|"
        r"(?:began|started) construction",
    ),
)
_AMBIGUOUS = re.compile(
    r"\b(?:may|might|could|possibly|reportedly|rumou?red|expected|proposed|not|never)\b", re.I
)
_CONTEXTUAL = re.compile(
    r"\b(?:hypothetical|illustrative|example|historical|historically|previously|formerly|"
    r"conditional|superseded|quotation|quoted|template|sample|fictional|synthetic|"
    r"if|unless|assuming|assume|would|prior|previous|archived|draft)\b",
    re.I,
)
_SCOPES = {
    "facility-expansion": ("construction",),
    "electrical-construction": ("construction", "electrical construction"),
    "construction": ("construction",),
    "construction-power": ("construction",),
    "temporary-power": ("temporary power", "construction power"),
    "commissioning-power": ("commissioning",),
    "commissioning": ("commissioning",),
    "production-power": ("production",),
    "production-electrification": ("production",),
}


def _normal(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.casefold()).strip()


def _subject_predicate(clause: str, references: list[str]) -> str | None:
    """Require the retained project itself to be the grammatical subject.

    A project mentioned in a comparison, quotation, contractor report or another
    project's sentence cannot lend its identity to that sentence's predicate.
    Only an optional second exact retained reference (the site address) can sit
    between the named subject and the supported predicate.
    """
    refs = sorted(
        {ref.strip() for ref in references if len(_normal(ref).split()) >= 2},
        key=len,
        reverse=True,
    )
    reference = "(?:" + "|".join(re.escape(ref) for ref in refs) + ")"
    if not refs:
        return None
    match = re.fullmatch(rf"{reference}(?: at {reference})?\s+(.+?)[.!?]?", clause.strip(), re.I)
    if not match:
        return None
    predicate = match[1].strip()
    predicate = re.sub(r"\s+as of \d{4}-\d{2}-\d{2}$", "", predicate, flags=re.I)
    return predicate


def extract_project_claims(
    text: str,
    *,
    references: list[str],
    activity_key: str,
    published_at: date | None,
    today: date,
) -> list[dict[str, Any]]:
    """Recognize affirmative exact-project clauses with explicit temporal provenance.

    Public claims are source reports only. In particular, MW values here do not
    mutate PowerNeed.required_mw and cannot meet official qualification gates.
    """
    # A current publication date cannot make a historical/example section current.
    # Unsupported document-level framing stays unknown instead of borrowing dates.
    if _CONTEXTUAL.search(text):
        return []
    result: list[dict[str, Any]] = []
    for match in re.finditer(r"[^\n]+?(?:[.!?](?=\s|$)|$)", text):
        quote = match.group().strip()
        if not quote or len(quote) > 1200:
            continue
        predicate = _subject_predicate(quote, references)
        if predicate is None:
            continue
        stamp = re.search(r"\bas of (\d{4}-\d{2}-\d{2})\b", quote, re.I)
        try:
            as_of = date.fromisoformat(stamp[1]) if stamp else published_at
        except ValueError:
            continue
        if as_of is None or as_of > today:
            continue

        metadata = {
            "activity_key": activity_key,
            "as_of": as_of.isoformat(),
            "date_basis": "explicit_as_of" if stamp else "publication_date",
            "quote": quote,
            "extraction_location": f"retrieved text chars {match.start()}:{match.end()}",
            "value_kind": "Reported",
        }

        def add(field: str, value: str, *, metadata: dict = metadata, **extra: Any) -> None:
            claim = {"field": field, "value": value, **metadata, **extra}
            if claim not in result:
                result.append(claim)

        ambiguous = bool(_AMBIGUOUS.search(quote))
        if not ambiguous and not re.search(
            r"\b(?:will|planned|scheduled|permit|approval)\b", quote, re.I
        ):
            for phase, pattern in _PHASES:
                if re.fullmatch(pattern, predicate, re.I):
                    add("phase", phase)
        service = r"(?:permanent (?:utility )?(?:power|service)|utility service)"
        if not ambiguous:
            if re.fullmatch(service + r"\s+(?:is |has been )energized", predicate, re.I):
                add("permanent_service", "energized")
            if re.fullmatch(
                service + r"\s+(?:is |remains )(?:pending|delayed|unavailable)", predicate, re.I
            ):
                add("permanent_service", "pending")
            # Facility-level demand is exact-project but deliberately not
            # activity-scoped; it remains distinct from temporary activity load.
            facility_demand = re.fullmatch(
                r"(?:planned )?facility (?:electrical )?demand is\s+(\d+(?:\.\d+)?)\s*(kW|MW)",
                predicate,
                re.I,
            )
            if (
                facility_demand
                and Decimal(facility_demand[1]) > 0
                and not re.search(
                    r"\b(?:campus|nameplate|capacity|generator|backup|temporary)\b", quote, re.I
                )
            ):
                mw = Decimal(facility_demand[1]) / (
                    1000 if facility_demand[2].casefold() == "kw" else 1
                )
                add("facility_demand_mw", format(mw.normalize(), "f"))
        scopes = _SCOPES.get(activity_key, (activity_key.replace("-", " "),))
        scope = next(
            (scope for scope in scopes if re.search(r"\b" + re.escape(scope) + r"\b", quote, re.I)),
            None,
        )
        if not scope:
            continue
        # Multiple activity subjects in a single clause are ambiguous: do not
        # transfer one activity's load or supply to another activity.
        activity_words = {"construction", "commissioning", "production"}
        if any(
            re.search(r"\b" + word + r"\b", quote, re.I)
            for word in activity_words
            if word not in scope
        ):
            continue
        # Negation is interpreted only in the exact supported supply expression;
        # it never makes an ambiguous load or future stage affirmative.
        if not _AMBIGUOUS.search(re.sub(r"\bnot adequate\b", "inadequate", quote, flags=re.I)):
            supply_predicate = re.fullmatch(
                re.escape(scope) + r" (?:power|service|supply) (?:is |remains )"
                r"(insufficient|inadequate|not adequate|adequate|sufficient)"
                r"(?: but (?:power|service|supply) (?:is |remains )"
                r"(insufficient|inadequate|not adequate|adequate|sufficient))?",
                predicate,
                re.I,
            )
            if supply_predicate:
                for supplied in supply_predicate.groups():
                    if supplied:
                        value = (
                            "adequate"
                            if supplied.lower() in {"adequate", "sufficient"}
                            else "insufficient"
                        )
                        add("supply_adequacy", value, reported_activity=scope)
        if not ambiguous:
            for value, pattern in (
                ("utility", r"temporary (?:power|service) is utility[- ]fed"),
                ("generator", r"temporary (?:power|service) is generator[- ]fed"),
            ):
                if re.fullmatch(re.escape(scope) + " " + pattern, predicate, re.I):
                    add("temporary_supply", value, reported_activity=scope)
            if not re.search(
                r"\b(?:campus|nameplate|eventual|total site|capacity|"
                r"generator rating|backup rating)\b",
                quote,
                re.I,
            ):
                load = re.fullmatch(
                    re.escape(scope)
                    + r" (?:requires|needs|electrical load is)\s+(\d+(?:\.\d+)?)\s*(kW|MW)",
                    predicate,
                    re.I,
                )
                if load and Decimal(load[1]) > 0:
                    mw = Decimal(load[1]) / (1000 if load[2].casefold() == "kw" else 1)
                    add("activity_load_mw", format(mw.normalize(), "f"), reported_activity=scope)
            voltage = re.fullmatch(
                re.escape(scope)
                + r" (?:temporary power|electrical) voltage (?:requirement )?is\s+"
                + r"(\d{2,4})\s*V,?\s*(\d)\s*(?:phase|ph)",
                predicate,
                re.I,
            )
            if voltage:
                add(
                    "voltage",
                    f"{int(voltage[1])} V, {int(voltage[2])} phase",
                    reported_activity=scope,
                )
            fuel = re.fullmatch(
                re.escape(scope)
                + r" (?:temporary power )?fuel (?:is |availability is )(available|unavailable)",
                predicate,
                re.I,
            )
            if fuel:
                add("fuel_availability", fuel[1].casefold(), reported_activity=scope)
            profile = re.fullmatch(
                re.escape(scope)
                + r" load profile is "
                + r"(continuous|intermittent|peaking|cyclic|variable|constant|24/7)",
                predicate,
                re.I,
            )
            if profile:
                add("load_profile", profile[1].casefold(), reported_activity=scope)
            procurement = re.fullmatch(
                re.escape(scope)
                + r" temporary power procurement is "
                + r"(underway|delayed|on hold|complete|not started)",
                predicate,
                re.I,
            )
            if procurement:
                add("procurement_status", procurement[1].casefold(), reported_activity=scope)
            obstacle = re.fullmatch(
                re.escape(scope)
                + r" utility interconnection is (pending|delayed|blocked|complete)",
                predicate,
                re.I,
            )
            if obstacle:
                add("utility_obstacle", obstacle[1].casefold(), reported_activity=scope)
            start = re.fullmatch(
                re.escape(scope)
                + r" (?:starts|begins|is scheduled to (?:start|begin)) on (\d{4}-\d{2}-\d{2})",
                predicate,
                re.I,
            )
            if start:
                try:
                    planned = date.fromisoformat(start[1])
                except ValueError:
                    continue
                add("activity_start", planned.isoformat(), reported_activity=scope, scheduled=True)
    framing = text
    # Only a supported sentence can own its terminal as-of date. A standalone
    # dated heading must not lend the publication date to an undated assertion.
    for quote in {claim["quote"] for claim in result}:
        without_stamp = re.sub(r"\s+as of \d{4}-\d{2}-\d{2}[.!?]?$", "", quote, flags=re.I)
        framing = framing.replace(quote, without_stamp)
    if re.search(r"\bas of \d{4}-\d{2}-\d{2}\b", framing, re.I):
        return []
    for reference in references:
        if reference:
            framing = re.sub(re.escape(reference), "", framing, flags=re.I)
    if any(int(year) < today.year for year in re.findall(r"\b(?:19|20)\d{2}\b", framing)):
        return []
    return result if len(result) <= 16 else []


def extract_retained_permit_claims(
    source_id: str, text: str, *, activity_key: str, as_of: date | None, today: date
) -> list[dict[str, Any]]:
    """Parse two reviewed retained permit formats without generalizing attribution."""
    if as_of is None or as_of > today:
        return []
    result: list[dict[str, Any]] = []
    if source_id in {"fort-worth-development-permits", "fort-worth-permits"}:
        # This adapter's work description can report facility scale. Keep it
        # separate from total electrical demand and generator requirement.
        from gridlens.ingestion.adapters.retained_permits import fields as permit_fields

        parsed = permit_fields(source_id, text)
        description = parsed.get("Work description")
        if description:
            match = re.search(r"(?<![\w.])(\d+(?:,\d{3})*(?:\.\d+)?)\s*MW\b", description[0], re.I)
            if match and Decimal(match[1].replace(",", "")) > 0:
                result.append(
                    {
                        "field": "facility_scale_mw",
                        "value": format(Decimal(match[1].replace(",", "")).normalize(), "f"),
                        "activity_key": activity_key,
                        "as_of": as_of.isoformat(),
                        "quote": description[1],
                        "value_kind": "Reported facility scale",
                    }
                )
    elif source_id == "boston-building-permits" and activity_key in {
        "temporary-power",
        "construction-power",
        "electrical-construction",
    }:
        from gridlens.ingestion.adapters.retained_permits import fields as permit_fields

        parsed = permit_fields(source_id, text)
        comments = parsed.get("Comments")
        if comments and re.search(r"\btemporary electrical work\b", comments[0], re.I):
            match = re.search(
                r"(?<!\d)(\d{2,4})\s*V\s*(\d{1,2})\s*Ph\b(?:[^\n]{0,80})?",
                comments[0],
                re.I,
            )
            if match:
                result.append(
                    {
                        "field": "voltage",
                        "value": f"{int(match[1])} V, {int(match[2])} phase",
                        "activity_key": activity_key,
                        "as_of": as_of.isoformat(),
                        "quote": comments[1],
                        "value_kind": "Permit-listed electrical constraint",
                    }
                )
    return result


def unparsed_adverse_text(text: str, claims: list[dict]) -> str:
    """Remove only recognized adverse phrases, never the surrounding clause.

    A clause can contain both a supported positive and an unparsed negative;
    retaining one does not authorize ignoring the other.
    """
    for quote in dict.fromkeys(claim["quote"] for claim in claims):
        remainder = quote
        for claim in (item for item in claims if item["quote"] == quote):
            patterns: list[str] = []
            if claim["field"] == "phase":
                patterns = [pattern for value, pattern in _PHASES if value == claim["value"]]
            elif claim["field"] == "permanent_service" and claim["value"] == "energized":
                patterns = [
                    r"(?:permanent (?:utility )?(?:power|service)|utility service)"
                    r"\s+(?:is |has been )energized\b"
                ]
            elif claim["field"] == "supply_adequacy":
                patterns = [
                    r"(?:power|service|supply)\s+(?:is |remains )"
                    r"(?:insufficient|inadequate|not adequate|adequate|sufficient)\b"
                ]
            for pattern in patterns:
                remainder = re.sub(pattern, "", remainder, flags=re.I)
        text = text.replace(quote, remainder)
    return text


class _ProjectClaimAccumulator:
    """Apply the canonical date/value rules while optionally retaining provenance."""

    def __init__(self, *, today: date, retain_claims: bool) -> None:
        self.today = today
        self.retain_claims = retain_claims
        self._values: dict[str, Any] = {field: None for field in FIELDS}
        self._has_value: dict[str, bool] = {field: False for field in FIELDS}
        self._conflict: dict[str, bool] = {field: False for field in FIELDS}
        self._claims: dict[str, list[dict]] = {field: [] for field in FIELDS}

    def add(self, claim: dict) -> None:
        field = claim.get("field")
        if field not in self._values:
            return
        try:
            dated = date.fromisoformat(claim["as_of"])
        except (KeyError, ValueError, TypeError):
            return
        persistent = claim.get("value") in {"completed", "cancelled", "adequate"}
        if dated > self.today or (dated < self.today - timedelta(days=90) and not persistent):
            return
        value = claim["value"]
        if not self._has_value[field]:
            self._values[field] = value
            self._has_value[field] = True
        elif self._values[field] != value:
            self._conflict[field] = True
        if self.retain_claims:
            self._claims[field].append(claim)

    def finish(self) -> dict[str, dict]:
        result = {}
        for field in FIELDS:
            has_value = self._has_value[field]
            state = {
                "status": (
                    "UNKNOWN"
                    if not has_value
                    else "CONFLICT"
                    if self._conflict[field]
                    else "SUPPORTED"
                ),
                "value": self._values[field] if has_value and not self._conflict[field] else None,
            }
            if self.retain_claims:
                state["claims"] = self._claims[field]
            result[field] = state
        return result


def _project_claim_accumulator(*, today: date, retain_claims: bool = False):
    return _ProjectClaimAccumulator(today=today, retain_claims=retain_claims)


def project_claim_state(claims: list[dict], *, today: date) -> dict[str, dict]:
    """Conflicting current source versions remain conflicts; never latest-URL wins."""
    accumulator = _project_claim_accumulator(today=today, retain_claims=True)
    for claim in claims:
        accumulator.add(claim)
    return accumulator.finish()


def qualification_veto(fields: dict[str, dict]) -> str | None:
    qualification_fields = {
        "phase",
        "permanent_service",
        "supply_adequacy",
        "temporary_supply",
        "activity_load_mw",
        "activity_start",
    }
    if any(fields.get(field, {}).get("status") == "CONFLICT" for field in qualification_fields):
        return "Current exact-activity public evidence has unresolved conflicting claims"
    phase = fields.get("phase", {})
    if phase.get("status") == "SUPPORTED" and phase.get("value") in {
        "paused",
        "completed",
        "cancelled",
    }:
        return "Current reported project phase does not support active qualification"
    supply = fields.get("supply_adequacy", {})
    if supply.get("status") == "SUPPORTED" and supply.get("value") == "adequate":
        return "Current reported suitable supply is adequate for this exact activity"
    return None
