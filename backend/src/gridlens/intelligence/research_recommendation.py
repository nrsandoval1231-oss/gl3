"""Deterministic advisory routing from current, source-bound project state."""

_NEED_FIELDS = ("activity", "tier", "mw", "timing", "duration", "supply")


def _supported(claim: object) -> bool:
    """A projected value counts as known only when current evidence backs it."""
    evidence = claim.get("evidence") if isinstance(claim, dict) else None
    return bool(
        isinstance(claim, dict)
        and claim.get("status") == "SUPPORTED"
        and claim.get("value") not in (None, "", [])
        and isinstance(evidence, list)
        and evidence
        and all(
            isinstance(item, dict)
            and item.get("id")
            and item.get("url")
            and item.get("support") == "accepted interpretation"
            for item in evidence
        )
    )


def _missing_facts(fields: dict, organizations: list[dict] | None = None) -> list[str]:
    missing = [
        key
        for key in ("identity", "site", "lifecycle", "activity", "power_need", "utility_service")
        if not _supported(fields.get(key))
    ]
    power_need = fields.get("power_need", {})
    if isinstance(power_need, dict) and isinstance(power_need.get("value"), list):
        nested = set()
        for need in power_need["value"]:
            if not isinstance(need, dict):
                nested.add("power_need[unknown]")
                continue
            activity = need.get("activity", {})
            activity_value = activity.get("value") if isinstance(activity, dict) else None
            label = activity_value.strip() if isinstance(activity_value, str) else "unknown"
            for field in _NEED_FIELDS:
                if not _supported(need.get(field)):
                    nested.add(f"power_need[{label}].{field}")
        missing.extend(sorted(nested))
    organizations = organizations or []
    grounded_parties = [
        item
        for item in organizations
        if item.get("organization")
        and any(
            isinstance(citation, dict)
            and citation.get("id")
            and citation.get("url")
            and citation.get("quote")
            for citation in item.get("citations", [])
        )
    ]
    if not any(
        any(
            token in str(item.get(key, "")).casefold()
            for token in ("owner", "operator", "developer")
        )
        for item in grounded_parties
        for key in ("category", "organization_relationship", "person_project_relationship")
    ):
        missing.append("company")
    if not _buyer_accessible(grounded_parties):
        missing.append("buyer")
    return missing


def _buyer_accessible(organizations: list[dict]) -> bool:
    return any(
        bool(item.get("public_contacts"))
        and bool(item.get("citations"))
        and any(
            keyword in str(item.get(field, "")).lower()
            for field in (
                "category",
                "organization_relationship",
                "person_project_relationship",
                "title",
            )
            for keyword in ("buyer", "procurement", "owner", "operator")
        )
        for item in organizations
    )


def research_recommended(
    *,
    material_change: bool,
    relevant: str,
    power_relevance: str,
    missing_facts: list[str],
    timing_known: bool,
    buyer_accessible: bool,
) -> bool:
    """Return true only for material, relevant evidence with actionable gaps."""
    # The parameters remain part of the public seam for legacy evaluators;
    # routing is strictly gated by Jev's labels and current grounded gaps.
    return bool(
        material_change
        and relevant == "YES"
        and power_relevance in {"MEDIUM", "HIGH"}
        and missing_facts
    )


def recommend_from_context(judgment: dict, state: dict) -> bool:
    """Apply deterministic routing to validated Jev labels and grounded state."""
    fields = state.get("state", {})
    organizations = state.get("organizations_and_roles", [])
    missing_facts = _missing_facts(fields, organizations)
    return research_recommended(
        material_change=judgment.get("material_change") == "YES",
        relevant=judgment.get("relevant", "UNKNOWN"),
        power_relevance=judgment.get("power_relevance", "UNKNOWN"),
        missing_facts=missing_facts,
        timing_known=False,
        buyer_accessible=False,
    )
