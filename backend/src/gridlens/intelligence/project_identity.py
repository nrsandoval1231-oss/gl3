from dataclasses import dataclass


@dataclass(frozen=True)
class MatchDecision:
    decision: str
    reason: str
    matched_facts: tuple[str, ...]


def decide_project_match(
    *,
    same_source_id: bool = False,
    same_address: bool = False,
    same_project_name: bool = False,
    same_asset_identity: bool = False,
    same_owner: bool = False,
    explicit_relationship: bool = False,
) -> MatchDecision:
    """Conservative identity gate. Company/owner alone can never merge projects."""
    facts = tuple(
        name
        for name, yes in (
            ("stable source id", same_source_id),
            ("physical address", same_address),
            ("project name/alias", same_project_name),
            ("asset identity", same_asset_identity),
            ("owner/developer", same_owner),
            ("explicit source relationship", explicit_relationship),
        )
        if yes
    )
    strong = same_source_id or same_asset_identity or explicit_relationship
    corroborated_site = same_address and same_project_name
    if strong or corroborated_site:
        return MatchDecision("matched", f"Identity supported by {', '.join(facts)}.", facts)
    return MatchDecision(
        "separate", "Insufficient identity evidence; ambiguous observations remain separate.", facts
    )
