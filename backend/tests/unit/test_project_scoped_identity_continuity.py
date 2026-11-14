"""Local company identity carries only across an unchanged reported role."""

from types import SimpleNamespace

import pytest

from gridlens.intelligence.identity_reconciliation import (
    _same_project_scoped_company_role_revision,
)


def context(
    *,
    organization="DataBank",
    current_organization=None,
    category="owner_developer",
    current_category=None,
    relationship="DIRECT",
    current_relationship=None,
):
    prior = SimpleNamespace(
        project_id="project-1",
        entity_key="same-normalized-company-key",
        person_name=None,
        organization=organization,
        category=category,
        organization_relationship=relationship,
        person_organization_relationship="UNKNOWN",
        person_project_relationship="UNKNOWN",
    )
    current = SimpleNamespace(
        project_id="project-1",
        entity_key="same-normalized-company-key",
        person_name=None,
        organization=current_organization or organization,
        category=current_category or category,
        organization_relationship=current_relationship or relationship,
        person_organization_relationship="UNKNOWN",
        person_project_relationship="UNKNOWN",
    )
    link = SimpleNamespace(
        entity_type="company",
        basis="project_scoped",
        source_evidence_id="old-evidence",
    )
    previous_candidate = {"stale": False, "suppressed": False, "correction_stale": False}
    prior_support = [
        {
            "id": "old-evidence",
            "url": "https://owner.example/red-oak",
            "supports": "project_organization",
            "quote": "DataBank develops Red Oak Campus with 480 MW.",
            "current_support": True,
        }
    ]
    current_citations = [
        {
            "url": "https://owner.example/red-oak",
            "quote": "DataBank develops Red Oak Campus with 640 MW.",
            "supports": "project_organization",
            "evidence_id": "new-evidence",
        }
    ]
    return prior, current, link, previous_candidate, prior_support, current_citations


def test_same_project_scoped_company_role_can_survive_nonidentity_source_revision():
    assert _same_project_scoped_company_role_revision(*context())


@pytest.mark.parametrize(
    "changes",
    [
        {
            "organization": "Example, Inc.",
            "current_organization": "Example LLC",
        },  # Same normalized stem, different legal form.
        {"current_category": "project_customer"},  # Ownership/development role changed.
        {"current_relationship": "UNKNOWN"},
    ],
)
def test_different_legal_entity_or_role_blocks_continuity(changes):
    assert not _same_project_scoped_company_role_revision(*context(**changes))


def test_project_change_withdrawal_suppression_or_correction_blocks_continuity():
    prior, current, link, candidate, old_support, citations = context()
    current.project_id = "project-2"
    assert not _same_project_scoped_company_role_revision(
        prior, current, link, candidate, old_support, citations
    )

    prior, current, link, candidate, old_support, citations = context()
    assert not _same_project_scoped_company_role_revision(
        prior, current, link, candidate, old_support, []
    )

    prior, current, link, candidate, old_support, citations = context()
    candidate["suppressed"] = True
    assert not _same_project_scoped_company_role_revision(
        prior, current, link, candidate, old_support, citations
    )

    prior, current, link, candidate, old_support, citations = context()
    candidate["correction_stale"] = True
    assert not _same_project_scoped_company_role_revision(
        prior, current, link, candidate, old_support, citations
    )


def test_nonproject_scoped_and_person_links_keep_their_existing_proof_rules():
    prior, current, link, candidate, old_support, citations = context()
    link.basis = "strong_identifier"
    assert not _same_project_scoped_company_role_revision(
        prior, current, link, candidate, old_support, citations
    )

    prior, current, link, candidate, old_support, citations = context()
    link.entity_type = "person"
    assert not _same_project_scoped_company_role_revision(
        prior, current, link, candidate, old_support, citations
    )


def test_new_role_must_be_supported_by_same_source_url():
    prior, current, link, candidate, old_support, citations = context()
    citations[0]["url"] = "https://other.example/red-oak"
    assert not _same_project_scoped_company_role_revision(
        prior, current, link, candidate, old_support, citations
    )
