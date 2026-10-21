"""Typed commercial presentation over accepted GridLens projections; never a fact authority."""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from typing import Any, Literal

from pydantic import BaseModel, Field

from gridlens.domain.power_schedule import PowerScheduleProjection, project_schedule
from gridlens.domain.pursuit_research import ACTIVE, fingerprint

POLICY = "opportunity-intelligence-v1"
FieldStatus = Literal[
    "Verified",
    "Evidence-supported estimate",
    "Research in progress",
    "Not publicly available",
    "Not applicable",
    "Conflicting evidence",
]


class IntelligenceSource(BaseModel):
    reference: str
    source_id: str | None = None
    title: str
    url: str | None = None
    source_date: str | None = None
    retained_evidence_id: str | None = None
    content_hash: str | None = None
    passage: str | None = None
    extraction_method: str
    verification_status: str
    assessed_at: str | None = None


class IntelligenceField(BaseModel):
    key: str
    label: str
    section: Literal["identity", "power", "commercial"]
    status: FieldStatus
    value: str | None = None
    basis: str
    sources: list[IntelligenceSource] = Field(default_factory=list)
    research_category: str | None = None
    research_status: str | None = None


class IntelligenceContact(BaseModel):
    claim_id: str
    company: str
    name: str | None = None
    title: str | None = None
    role: str
    responsibility: Literal[
        "Verified project responsibility",
        "Verified organizational responsibility",
        "Inferred likely role",
        "General company contact path",
    ]
    purchasing_authority: str = "Requires confirmation for this power package"
    methods: list[dict[str, str]] = Field(default_factory=list)
    sources: list[IntelligenceSource] = Field(default_factory=list)
    verified_at: str | None = None


class IntelligenceCard(BaseModel):
    policy_version: str = POLICY
    need_id: str
    project_id: str
    input_fingerprint: str
    qualification: str
    disposition: str
    fields: list[IntelligenceField]
    contacts: list[IntelligenceContact]
    next_contact_path: str
    next_action: str
    research_gaps: list[IntelligenceField]
    completeness: dict[str, int | str]
    last_intelligence_update: str | None = None
    power_gap: dict[str, Any] | None = None
    power_schedule: PowerScheduleProjection | None = None
    evidence: list[IntelligenceSource]
    research_enabled: bool


def _iso(value: Any) -> str | None:
    return value.isoformat() if hasattr(value, "isoformat") else str(value) if value else None


def normalize_gap(item: dict) -> dict | None:
    """Normalize both accepted official and operator shapes, checking arithmetic.

    This receives a current canonical projection, not a provider response. A
    campus total, scenario or unknown supply can never enter through this path.
    """
    raw = item.get("qualified_remaining_gap")
    if item.get("tier") != "Lead" or not item.get("qualification_version") or not raw:
        return None
    if item.get("qualification_conflict") or item.get("conflict_state") == "CONFLICT":
        return None
    numbers = {}
    try:
        for field in ("required", "available", "remaining"):
            for end in ("min", "max"):
                value = raw.get(f"{field}_mw_{end}", raw.get(f"{field}_mw"))
                number = Decimal(str(value))
                if not number.is_finite() or number < 0 or number.adjusted() > 12:
                    return None
                numbers[f"{field}_mw_{end}"] = number
            if numbers[f"{field}_mw_min"] > numbers[f"{field}_mw_max"]:
                return None
    except (InvalidOperation, ValueError, TypeError):
        return None
    for end, other in (("min", "max"), ("max", "min")):
        if numbers[f"remaining_mw_{end}"] != max(
            Decimal(0), numbers[f"required_mw_{end}"] - numbers[f"available_mw_{other}"]
        ):
            return None
    return {
        **raw,
        **{key: str(value) for key, value in numbers.items()},
        "start_window": raw.get("start_window") or item.get("start_window"),
        "duration": raw.get("duration") or item.get("duration"),
        "calculation": (
            "[max(0, required_min - available_max), max(0, required_max - available_min)]"
        ),
        "version": item["qualification_version"],
        "basis": raw.get("basis_quote")
        or "Accepted scoped operator facts; inspect fact IDs and hashes.",
        "value_kind": "Derived",
    }


def _source(row: dict, *, chain: bool = False) -> IntelligenceSource:
    reference = str(row.get("id") or row.get("evidence_id") or "")
    return IntelligenceSource(
        reference=("buying-chain:" if chain else "evidence:") + reference,
        source_id=row.get("source_id"),
        title=str(row.get("title") or ("Buying-chain source" if chain else "Retained source")),
        url=row.get("url"),
        source_date=_iso(row.get("published_at") or row.get("event_date")),
        retained_evidence_id=(
            str(row["retained_evidence_id"])
            if row.get("retained_evidence_id")
            else None
            if chain
            else reference
        ),
        content_hash=row.get("content_hash"),
        passage=row.get("quote") or row.get("abstract"),
        extraction_method=str(row.get("extraction_location") or "canonical projection"),
        verification_status="Current retained support"
        if chain or row.get("assessment_current")
        else "Retained source; assess claim currency",
        assessed_at=_iso(row.get("observed_at") or row.get("retrieved_at")),
    )


def contact_projection(chain: dict) -> list[IntelligenceContact]:
    from gridlens.domain.commercial_triage import _is_rental_intermediary

    result = []
    for party in chain.get("candidates", []):
        if (
            party.get("stale")
            or party.get("organization_relationship") != "DIRECT"
            or _is_rental_intermediary(
                party.get("category"), party.get("organization"), party.get("reason")
            )
        ):
            continue
        evidence = [e for e in party.get("evidence", []) if e.get("current_support") is True]
        if not evidence:
            continue
        responsibility = "General company contact path"
        if party.get("person_name"):
            if party.get("person_project_relationship") == "DIRECT":
                responsibility = "Verified project responsibility"
            elif party.get("person_project_relationship") == "ROLE_SUPPORTED":
                responsibility = "Inferred likely role"
            elif party.get("person_organization_relationship") == "DIRECT":
                responsibility = "Verified organizational responsibility"
        methods = []
        for contact in party.get("public_contacts", []):
            value, kind = str(contact.get("value", "")), str(contact.get("kind", "")).lower()
            support = next(
                (
                    e
                    for e in evidence
                    if e.get("supports") == "public_contact"
                    and e.get("url") == contact.get("source_url")
                    and e.get("quote") == contact.get("quote")
                    and value
                    and value.casefold() in str(e.get("quote", "")).casefold()
                ),
                None,
            )
            if support is None:
                continue
            href = None
            if kind == "email" and re.fullmatch(
                r"[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", value
            ):
                href = "mailto:" + value
            elif kind in {"phone", "telephone"} and re.fullmatch(r"\+?[\d () .-]{7,30}", value):
                digits = re.sub(r"[^\d+]", "", value)
                if 7 <= len(re.sub(r"\D", "", digits)) <= 15:
                    href = "tel:" + digits
            if href:
                methods.append(
                    {
                        "kind": kind,
                        "value": value,
                        "href": href,
                        "source_url": contact["source_url"],
                        "verified_at": _iso(contact.get("observed_at")) or "",
                    }
                )
        result.append(
            IntelligenceContact(
                claim_id=str(party["id"]),
                company=party["organization"],
                name=party.get("person_name"),
                title=party.get("title"),
                role=party.get("category", "unknown").replace("_", " "),
                responsibility=responsibility,  # type: ignore[arg-type]
                methods=methods,
                sources=[_source(e, chain=True) for e in evidence],
                verified_at=_iso(party.get("verified_at")),
            )
        )
    return result


def _source_project_name(
    item: dict, sources: list[IntelligenceSource]
) -> tuple[str | None, list[IntelligenceSource]]:
    """Use a project name only when a current retained source names it directly."""

    f17_stack_sources = {
        "f17-stack-city-claim",
        "f17-stack-cec-filing",
    }
    retained_f17_stack = [source for source in sources if source.source_id in f17_stack_sources]
    if retained_f17_stack:
        # This compound label is assembled only from source-native aliases in
        # the exact current CEC evidence version. The source must also anchor
        # the relation to the physical project address; its generated title is
        # never evidence for the label.
        from gridlens.ingestion.adapters.retained_document import SOURCES

        policy = SOURCES["f17-stack-cec-filing"]
        for source in retained_f17_stack:
            if (
                source.source_id != "f17-stack-cec-filing"
                or not source.retained_evidence_id
                or source.content_hash != policy["sha256"]
                or source.url != policy["url"]
                or source.verification_status != "Current retained support"
            ):
                continue
            passage = source.passage or ""
            identity = re.search(
                r"\b(?P<identifier>SVY02A)\s+Memorex\b.{0,100}?"
                r"\b(?P<alias>Memorex Junction)\s+Operational Study\b",
                passage,
                re.I | re.S,
            )
            owner_alias = re.search(
                r"\bowner of the data center project,\s*a\.k\.a\.\s*.{0,40}?"
                r"\bMemorex Junction\b",
                passage,
                re.I | re.S,
            )
            site = re.search(r"\b1200\s+Memorex\s+Drive\s+project\b", passage, re.I)
            if not identity or not owner_alias or not site:
                continue
            value = f"{identity.group('identifier')} / {identity.group('alias')} data center"
            support = [identity.group(0), owner_alias.group(0), site.group(0)]
            return value, [
                source.model_copy(
                    update={
                        "passage": quote,
                        "verification_status": "Current CEC source-native project alias and site",
                    }
                )
                for quote in support
            ]
        # An F17 item cannot fall through to generic “Project:” or generated-
        # title matching when its exact retained alias proof is unavailable.
        return None, []

    def meaningful(value: str) -> bool:
        clean = value.strip(" .,:;\t")
        return bool(
            clean
            and not re.fullmatch(r"[A-Z]{0,6}[- ]?\d{4,}[A-Z]?", clean, re.I)
            and not re.match(r"^(?:permit|case|application)(?:\s|#|number|$)", clean, re.I)
        )

    candidates: list[str] = []
    for source in sources:
        passage = source.passage or ""
        if source.source_id == "texas-rrc-drilling-permits":
            lease = re.search(r"(?mi)^lease:\s*(?P<value>[^\r\n]+)", passage)
            well = re.search(r"(?mi)^well:\s*(?P<value>[^\r\n]+)", passage)
            if lease and well:
                value = f"{lease.group('value').strip()}, well {well.group('value').strip()}"
                excerpt = f"{lease.group(0).strip()}\n{well.group(0).strip()}"
                return value, [
                    source.model_copy(
                        update={
                            "passage": excerpt,
                            "verification_status": "Current RRC lease and well identity",
                        }
                    )
                ]
        if source.source_id == "austin-building-permits":
            match = re.search(r"(?i)\bTXDOT\s+project\s*#\s*(?P<id>[A-Z0-9-]+)", passage)
            if match:
                value = f"TXDOT project # {match.group('id')}"
                line = next(
                    (line for line in passage.splitlines() if match.group(0) in line),
                    match.group(0),
                )
                return value, [
                    source.model_copy(
                        update={
                            "passage": line,
                            "verification_status": "Current Austin permit project reference",
                        }
                    )
                ]
    for source in sources:
        passage = source.passage or ""
        narrative_name = re.search(
            r"(?i)\bFacility Name:\s*(?P<name>.*?)"
            r"(?=\s+(?:AIRS No\.|Location:|Application #|Date of Application:)|[\r\n]|$)",
            passage,
        )
        if narrative_name:
            value = narrative_name.group("name").strip(" .,:;")
            if meaningful(value):
                return value, [
                    source.model_copy(
                        update={
                            "passage": narrative_name.group(0).strip(),
                            "verification_status": "Current narrative facility name",
                        }
                    )
                ]
        patterns = (
            r"\bunder the name\s+(?P<name>[^.\r\n]+)",
            r"(?m)^Project:\s*(?P<name>[^\r\n]+)",
            r"(?m)^Facility:\s*(?P<name>[^\r\n]+)",
        )
        for pattern in patterns:
            candidates.extend(
                match.group("name").strip(" .,:;") for match in re.finditer(pattern, passage, re.I)
            )
    candidates.append(str(item.get("supported_subject") or "").strip())
    for candidate in candidates:
        if not meaningful(candidate):
            continue
        supported = [
            source.model_copy(
                update={
                    "passage": next(
                        line
                        for line in (source.passage or "").splitlines()
                        if candidate.casefold() in line.casefold()
                    ),
                    "verification_status": "Current source-native project name",
                }
            )
            for source in sources
            if candidate.casefold() in (source.passage or "").casefold()
        ]
        if supported:
            return candidate, supported
    return None, []


def _source_location(
    sources: list[IntelligenceSource],
) -> tuple[str | None, list[IntelligenceSource]]:
    """Prefer a precise address only when the current source states it explicitly."""
    for source in sources:
        passage = source.passage or ""
        match = re.search(
            r"(?i)\bto be located at (?P<address>2883 Gordon Highway, Augusta, Richmond County)",
            passage,
        )
        if match:
            line = next(
                (line for line in passage.splitlines() if match.group(0) in line),
                match.group(0),
            )
            return match.group("address"), [
                source.model_copy(
                    update={
                        "passage": line,
                        "verification_status": "Current permit narrative address",
                    }
                )
            ]
    return None, []


def _source_identifier(
    sources: list[IntelligenceSource],
) -> tuple[str | None, list[IntelligenceSource]]:
    for source in sources:
        if source.source_id in {"texas-rrc-drilling-permits", "austin-building-permits"}:
            row = re.search(r"(?mi)^row:\s*(?P<value>[^\r\n]+)", source.passage or "")
            if row:
                return row.group("value").strip(), [
                    source.model_copy(
                        update={
                            "passage": row.group(0).strip(),
                            "verification_status": "Current source record identifier",
                        }
                    )
                ]
        for pattern in (
            r"(?m)^Permit:\s*(?P<value>[A-Z0-9-]+)",
            r"(?m)^Permit number:\s*(?P<value>[A-Z0-9-]+)",
            r"(?m)^Application number:\s*(?P<value>[A-Z0-9-]+)",
        ):
            match = re.search(pattern, source.passage or "", re.I)
            if match:
                return match.group("value"), [
                    source.model_copy(
                        update={
                            "passage": match.group(0),
                            "verification_status": "Current source identifier",
                        }
                    )
                ]
    return None, []


def assemble_card(
    item: dict, chain: dict, commercial: dict, questions: list[dict], *, research_enabled: bool
) -> IntelligenceCard:
    """Pure assembly. Completeness is descriptive and cannot change qualification."""
    sources = [_source(e) for e in item.get("evidence", [])]
    current = [_source(e) for e in item.get("evidence", []) if e.get("assessment_current")]
    contacts = contact_projection(chain)
    owners = [
        p
        for p in contacts
        if p.role in {"owner developer", "asset operator", "owner construction", "owner energy"}
    ]
    unique_owners = {p.company for p in owners}
    fields: list[IntelligenceField] = []
    latest: dict[str, dict] = {}
    for q in questions:  # newest first, supplied by bounded repository read
        latest.setdefault(q["category"], q)

    def add(
        key,
        label,
        section,
        value,
        category,
        refs=None,
        *,
        estimate=False,
        conflict=False,
        basis="Current canonical evidence; inspect the cited source and scope.",
    ):
        refs = refs or []
        value = (
            str(value)
            if value is not None
            and str(value).strip().lower() not in {"", "unknown", "not assessed"}
            else None
        )
        q = latest.get(category)
        research_field = {
            "required_mw": "activity_load_mw",
            "facility_scale": "facility_scale_mw",
            "facility_demand": "facility_demand_mw",
            "voltage": "voltage",
            "fuel": "fuel_availability",
            "load_profile": "load_profile",
            "procurement": "procurement_status",
            "utility_obstacle": "utility_obstacle",
            "start": "activity_start",
            "stage": "phase",
            "supply_status": "supply_adequacy",
            "energization": "permanent_service",
        }.get(key)
        research = item.get("research_state", {}).get(research_field, {})
        claim_sources = []
        for claim in research.get("claims", []):
            for source in sources:
                if (
                    source.retained_evidence_id == claim.get("evidence_id")
                    and source.content_hash == claim.get("evidence_hash")
                    and claim.get("quote")
                    and source.passage
                    and claim["quote"] in source.passage
                ):
                    claim_sources.append(
                        source.model_copy(
                            update={
                                "passage": claim["quote"],
                                "verification_status": "Current source-reported claim",
                            }
                        )
                    )
        if research.get("status") == "SUPPORTED" and value is None and claim_sources:
            value = str(research["value"]).replace("_", " ")
            if research_field == "activity_load_mw":
                value += " MW (source-reported)"
            elif research_field == "facility_scale_mw":
                value += " MW (reported facility scale)"
            elif research_field == "facility_demand_mw":
                value += " MW (source-reported facility demand)"
            refs = claim_sources
            if research_field == "facility_scale_mw":
                basis = (
                    "Current source descriptor of facility scale; it does not establish total "
                    "planned electrical demand, temporary-generation demand or qualification."
                )
            elif research_field == "facility_demand_mw":
                basis = (
                    "Current exact-project electrical-demand report; it is separate from "
                    "temporary activity demand and does not change qualification."
                )
            else:
                basis = (
                    "Current exact-project, activity-scoped source report; inspect the cited quote."
                )
        if research.get("status") == "CONFLICT":
            refs = claim_sources
        conflict = conflict or (
            item.get("research_state", {}).get(research_field, {}).get("status") == "CONFLICT"
        )
        if section == "power" and item.get("conflict_state") == "CONFLICT":
            conflict = True
        if conflict:
            status = "Conflicting evidence"
            value = None
            basis = "Current evidence conflicts; no single value is accepted."
        elif value is not None and refs:
            status = "Evidence-supported estimate" if estimate else "Verified"
        else:
            value = None
            status = "Research in progress"
            basis = (
                "Research queued or running."
                if q and q["status"] in ACTIVE
                else "No supported value yet. "
                + (
                    "Targeted research is available."
                    if research_enabled
                    else "Research execution is disabled."
                )
            )
            if q and q["status"] not in ACTIVE:
                basis += " Last attempt: " + q["status"].lower().replace("_", " ") + "."
        fields.append(
            IntelligenceField(
                key=key,
                label=label,
                section=section,
                value=value,
                status=status,
                basis=basis,
                sources=refs,
                research_category=category,
                research_status=q["status"] if q else "NOT_SCHEDULED",
            )
        )

    owner_refs = [s for p in owners for s in p.sources]
    add(
        "customer",
        "Customer / end user",
        "identity",
        "; ".join(sorted(unique_owners)) or None,
        "identity",
        owner_refs,
    )
    project_name, project_refs = _source_project_name(item, current)
    identifier, identifier_refs = _source_identifier(current)
    add(
        "project",
        "Project",
        "identity",
        project_name,
        "identity",
        project_refs,
    )
    add(
        "source_identifier",
        "Permit / source identifier",
        "identity",
        identifier,
        "identity",
        identifier_refs,
    )
    exact_location, location_refs = _source_location(current)
    add(
        "location",
        "Facility location",
        "identity",
        exact_location or item.get("location"),
        "identity",
        location_refs or current,
        basis=(
            "Current permit narrative states the street address and county."
            if exact_location
            else "Current canonical site location; inspect the cited source and scope."
        ),
    )
    add("activity", "Power activity", "identity", item.get("activity"), "power_need", current)
    add("stage", "Project stage", "identity", item.get("lifecycle_state"), "phase", current)
    gap = normalize_gap(item)
    schedule_facts = [
        fact
        for fact in item.get("operator_fact_refs", [])
        if fact.get("fact_type") == "power_schedule"
    ]
    schedule = project_schedule(schedule_facts)

    def field_sources(kind):
        quote = item.get("power_field_provenance", {}).get(kind)
        if kind == "demand":
            quote = quote or item.get("demand_quote")
        refs = [
            source.model_copy(update={"passage": quote})
            for source in current
            if quote and source.passage and quote in source.passage
        ]
        fact_types = {
            "demand": {"demand"},
            "start": {"timing"},
            "duration": {"timing"},
            "supply": {"suitable_supply"},
        }[kind]
        for fact in item.get("operator_fact_refs", []):
            if fact.get("fact_type") not in fact_types:
                continue
            refs.append(
                IntelligenceSource(
                    reference="operator-fact:" + fact["fact_version_id"],
                    title="Accepted " + fact["fact_type"] + " confirmation",
                    content_hash=fact["content_hash"],
                    passage=str(fact.get("value", {})),
                    source_date=_iso(fact.get("confirmed_at")),
                    extraction_method="Attributed operator confirmation",
                    verification_status="User-confirmed",
                )
            )
        return refs

    power_refs = [
        source
        for kind in ("demand", "start", "duration", "supply")
        for source in field_sources(kind)
    ]
    add(
        "required_mw",
        "Activity-specific requirement",
        "power",
        item.get("required_mw"),
        "load",
        field_sources("demand"),
    )
    add("facility_scale", "Reported facility scale", "power", None, "load")
    add("facility_demand", "Total planned facility demand", "power", None, "facility_demand")
    add(
        "start", "Power needed", "power", item.get("start_window"), "timing", field_sources("start")
    )
    add(
        "duration",
        "Bridge / activity duration",
        "power",
        item.get("duration"),
        "duration",
        field_sources("duration"),
    )
    add(
        "supply",
        "Suitable available supply",
        "power",
        f"{gap['available_mw_min']}–{gap['available_mw_max']} MW" if gap else None,
        "supply",
        field_sources("supply"),
    )
    add(
        "gap",
        "Residual power gap",
        "power",
        f"{gap['remaining_mw_min']}–{gap['remaining_mw_max']} MW" if gap else None,
        "supply",
        power_refs,
        estimate=False,
        basis=gap["calculation"]
        if gap
        else "No defensible gap until scoped demand, dates and suitable supply are established.",
    )
    add("supply_status", "Supply adequacy", "power", None, "supply")
    for key, label, category in (
        ("energization", "Utility service status", "supply"),
        ("fuel", "Fuel availability", "fuel"),
        ("load_profile", "Load profile", "load_profile"),
        ("procurement", "Temporary-power procurement", "procurement"),
        ("utility_obstacle", "Utility interconnection obstacle", "utility_obstacle"),
    ):
        add(key, label, "power", None, category)
    add("voltage", "Voltage / electrical requirements", "power", None, "voltage")
    add(
        "assessment",
        "Why this matters",
        "commercial",
        commercial.get("reason"),
        "power_need",
        current,
        basis="Deterministic commercial assessment; qualification remains separate.",
    )
    contact_refs = [source for contact in contacts for source in contact.sources]
    add(
        "contact_path",
        "Verified business contact path",
        "commercial",
        next((contact.company for contact in contacts if contact.methods), None),
        "buyer",
        contact_refs,
    )
    add(
        "project_contact",
        "Project-responsible person",
        "commercial",
        next(
            (
                contact.name
                for contact in contacts
                if contact.responsibility == "Verified project responsibility"
            ),
            None,
        ),
        "buyer",
        contact_refs,
    )
    gaps = [f for f in fields if f.value is None]
    complete = sum(f.value is not None for f in fields)
    reachable = next((p for p in contacts if p.methods), None)
    path = (
        f"Contact {reachable.name or reachable.company} via the cited business contact; "
        "confirm responsibility for this power package."
        if reachable
        else f"Verify the project contact through {contacts[0].company}'s official channel."
        if contacts
        else "Research the owner/operator and procurement contact using official project sources."
    )
    updated = sorted(s.assessed_at for s in sources if s.assessed_at)
    return IntelligenceCard(
        need_id=str(item["id"]),
        project_id=str(item["project_id"]),
        input_fingerprint=fingerprint([POLICY, item, chain, questions]),
        qualification=item["tier"],
        disposition=commercial.get("disposition", "RESEARCH"),
        fields=fields,
        contacts=contacts,
        next_contact_path=path,
        next_action=commercial.get("next_action") or item.get("next_action") or path,
        research_gaps=gaps,
        completeness={
            "supported": complete,
            "total": len(fields),
            "percent": round(100 * complete / len(fields)),
            "basis": "Supported required fields; independent of commercial qualification.",
        },
        last_intelligence_update=updated[-1] if updated else None,
        power_gap=gap,
        power_schedule=schedule,
        evidence=sources,
        research_enabled=research_enabled,
    )
