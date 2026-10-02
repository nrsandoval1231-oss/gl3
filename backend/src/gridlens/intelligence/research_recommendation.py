"""Deterministic, advisory research routing seam; never queues work or changes tiers."""


def research_recommended(
    *,
    material_change: bool,
    relevant: str,
    power_relevance: str,
    missing_facts: list[str],
    timing_known: bool,
    buyer_accessible: bool,
) -> bool:
    return bool(
        material_change
        and relevant == "YES"
        and power_relevance in {"MEDIUM", "HIGH"}
        and missing_facts
        and (not timing_known or not buyer_accessible)
    )


def recommend_from_context(judgment: dict, state: dict) -> bool:
    """Apply deterministic routing to a bounded state and a validated shadow judgment."""
    fields = state.get("state", {})
    missing_facts = [
        key
        for key in ("power_need", "utility_service", "lifecycle", "activity")
        if fields.get(key, {}).get("status") != "SUPPORTED"
    ]
    utility = fields.get("utility_service", {})
    utility_known = utility.get("status") == "SUPPORTED" and bool(utility.get("value"))
    power_need = fields.get("power_need", {})
    power_need_rows = power_need.get("value") if power_need.get("status") == "SUPPORTED" else []
    timing_known = utility_known or any(
        isinstance(need, dict)
        and need.get("timing", {}).get("status") == "SUPPORTED"
        and bool(need.get("timing", {}).get("value"))
        for need in (power_need_rows or [])
    )
    buyer_accessible = any(
        bool(item.get("public_contacts"))
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
        for item in state.get("organizations_and_roles", [])
    )
    return research_recommended(
        material_change=judgment.get("material_change") == "YES",
        relevant=judgment.get("relevant", "UNKNOWN"),
        power_relevance=judgment.get("power_relevance", "UNKNOWN"),
        missing_facts=missing_facts,
        timing_known=timing_known,
        buyer_accessible=buyer_accessible,
    )
