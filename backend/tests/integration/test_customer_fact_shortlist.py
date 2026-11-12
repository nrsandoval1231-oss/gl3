"""Typed build facts extend the existing source shortlist; never rental demand."""

from copy import deepcopy

import pytest
from sqlalchemy import select

from gridlens.intelligence.account_shortlist import assess_generation
from gridlens.intelligence.customer_intelligence import project_customer_facts
from gridlens.persistence.models import (
    BrowseCustomerMembership,
    BrowseGeneration,
    BrowseRow,
    CompanyIdentity,
)

pytest_plugins = ["test_equipment_intelligence"]


def seed_facts(session, monkeypatch):
    from test_equipment_intelligence import publish_test_browse, seed

    rows = seed(
        session, body="Mock Permian Compression Station has 120 MW of campus development capacity."
    )
    need, project, observation, evidence, interpretation, _source = rows
    publish_test_browse(session, monkeypatch, [(need, project)])
    browse = session.scalar(select(BrowseRow))
    facts = project_customer_facts(session, [project.id], generation=None)[str(project.id)]
    browse.compact = {**browse.compact, "customer_facts": facts, "required_mw": None}
    browse.summary = {"name": project.name, "evidence": []}
    company = CompanyIdentity()
    session.add(company)
    session.flush()
    session.add(
        BrowseCustomerMembership(
            generation_id=browse.generation_id,
            company_identity_id=company.id,
            project_id=project.id,
            organization_name="Canonical Customer",
            role="owner_developer",
        )
    )
    session.flush()
    generation = session.get(BrowseGeneration, browse.generation_id)
    return rows, browse, generation


def test_capacity_only_source_enters_existing_canonical_customer_shortlist(
    equipment_db, monkeypatch
):
    from gridlens.intelligence.customer_results import groups

    with equipment_db.begin() as session:
        rows, browse, generation = seed_facts(session, monkeypatch)
        need, _project, _observation, _evidence, _interpretation, _source = rows
        without = deepcopy(browse.compact)
        browse.compact = {**without, "customer_facts": []}
        session.flush()
        assert not assess_generation(session, generation)["eligible_need_ids"]
        # A new coherent generation/cache identity is required after frozen input changes.
        browse.compact = without
        generation.digest = "b" * 64
        session.flush()
        assessed = assess_generation(session, generation)
        assert assessed["eligible_need_ids"] == [need.id]
        assert "rental requirement" in " ".join(assessed["assessments"][str(need.id)]["reasons"])
        result = groups(session, selected_generation=generation, shortlist=True)
        assert result["total"] == 1
        assert result["items"][0]["group_kind"] == "resolved_identity"
        assert need.required_mw is None and browse.mw_low is None


@pytest.mark.parametrize("corruption", ["hash", "withdrawn", "conflict", "jev_hold"])
def test_typed_eligibility_refuses_unbound_conflicted_or_withdrawn_source(
    equipment_db, monkeypatch, corruption
):
    from gridlens.intelligence import account_shortlist

    with equipment_db.begin() as session:
        rows, browse, generation = seed_facts(session, monkeypatch)
        need, _project, _observation, evidence, interpretation, _source = rows
        assert assess_generation(session, generation)["eligible_need_ids"] == [need.id]
        if corruption == "withdrawn":
            interpretation.status = "rejected"
        elif corruption == "jev_hold":
            monkeypatch.setattr(
                account_shortlist,
                "_current_jev_decisions",
                lambda *_args: {str(evidence.id): "HOLD"},
            )
        else:
            facts = deepcopy(browse.compact["customer_facts"])
            claim = facts[0]["capacity_claims"][0]
            if corruption == "hash":
                claim["source"]["content_hash"] = "f" * 64
            else:
                facts[0]["capacity_claims"].append(
                    {**deepcopy(claim), "fact_id": "conflict-fact", "value_mw": "900"}
                )
            browse.compact = {**browse.compact, "customer_facts": facts}
            generation.digest = "c" * 64
        session.flush()
        result = assess_generation(session, generation)
        assert not result["eligible_need_ids"]
