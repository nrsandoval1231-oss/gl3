"""Prior-run company receipts preserve local IDs, never current source support."""

import hashlib
from copy import deepcopy
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from gridlens.intelligence.identity_reconciliation import (
    _adjacent_prior_retained_evidence_versions,
    _prior_run_receipt_scope_is_unambiguous,
    _retained_company_project_history_is_safe,
    _same_prior_run_project_scoped_company_role_revision,
)


def test_prior_run_receipt_requires_nonempty_latest_run_and_one_identity():
    base = {
        "latest_run_claim_ids": {"claim-a"},
        "matching_claim_ids": {"claim-a"},
        "selected_claim_id": "claim-a",
        "company_identity_ids": {"company-a"},
    }
    assert _prior_run_receipt_scope_is_unambiguous(**base)
    for changes in (
        {"latest_run_claim_ids": set()},
        {"matching_claim_ids": set()},
        {"selected_claim_id": "claim-b"},
        {"company_identity_ids": {"company-a", "company-b"}},
    ):
        assert not _prior_run_receipt_scope_is_unambiguous(**(base | changes))


def test_prior_run_receipt_rejects_discarded_conflicting_identity_ids():
    assert not _prior_run_receipt_scope_is_unambiguous(
        latest_run_claim_ids={"claim-a", "claim-b"},
        matching_claim_ids={"claim-a", "claim-b"},
        selected_claim_id="claim-a",
        company_identity_ids={"project-scoped-id", "strong-identity-id"},
    )


def test_prior_evidence_must_be_immediately_before_current_accepted_version():
    old_time = datetime(2026, 11, 12, tzinfo=UTC)
    new_time = old_time + timedelta(seconds=1)
    prior = SimpleNamespace(id="a", observation_id="obs", observed_at=old_time)
    current = SimpleNamespace(id="c", observation_id="obs", observed_at=new_time)
    intermediate = SimpleNamespace(id="b", observation_id="obs", observed_at=old_time)
    assert _adjacent_prior_retained_evidence_versions(prior, current, [current, prior])
    assert not _adjacent_prior_retained_evidence_versions(prior, current, [current, intermediate])
    current.observation_id = "other-observation"
    assert not _adjacent_prior_retained_evidence_versions(prior, current, [current, prior])
    current.observation_id = "obs"
    current.observed_at = old_time
    assert not _adjacent_prior_retained_evidence_versions(prior, current, [current, prior])


def _retained_version(evidence_id: str, *, adverse: bool = False, metadata: bool = False):
    from gridlens.ingestion.adapters.retained_company_projects import (
        RETRIEVAL_METHOD,
        SOURCE_ID,
        retained_record_hash,
        retained_records,
    )

    root = Path(__file__).resolve().parents[3]
    records, _held = retained_records(root / "eval/customer-commercial-v1")
    record = deepcopy(
        next(
            item
            for item in records
            if any(
                "sources/databank.json" in source
                for source in item["retained_company_project"]["source_files"]
            )
        )
    )
    context = record["retained_company_project"]
    if metadata:
        record["publication_date_metadata"] = record["publication_date"]
        context["publication_date_metadata"] = record["publication_date_metadata"]
        record["source_hash"] = retained_record_hash(record)
        context["content_hash"] = record["source_hash"]
    if adverse:
        record["title"] = "Red Oak Campus canceled"
        record["abstract"] = (
            record.get("abstract") or ""
        ) + "\n\nThe Red Oak Campus was canceled and will not proceed."
        context["body_hash"] = hashlib.sha256(record["abstract"].encode("utf-8")).hexdigest()
        context["status"] = "adverse_status_review"
        context["status_quote"] = "The Red Oak Campus was canceled"
        record["source_hash"] = retained_record_hash(record)
        context["content_hash"] = record["source_hash"]
    return SimpleNamespace(
        id=evidence_id,
        title=record["title"],
        abstract=record["abstract"],
        url=record["html_url"],
        published_at=date.fromisoformat(record["publication_date"]),
        content_hash=record["source_hash"],
        provenance={
            "retained_company_project": context,
            "source_id": SOURCE_ID,
            "retrieval_method": RETRIEVAL_METHOD,
        },
    )


def test_replayed_historical_adverse_version_blocks_receipt_even_when_reused():
    # B was first observed before A, then replayed after A without creating a
    # second immutable Evidence row. Its adverse marker still blocks A → C.
    version_a = _retained_version("accepted-a")
    version_b = _retained_version("withdrawn-b", adverse=True)
    version_c = _retained_version("accepted-c")
    assert not _retained_company_project_history_is_safe(
        [version_c, version_a, version_b],
        source_id="retained-company-project-evaluation",
        schema_version="retained-company-project-v2",
    )


def test_native_history_requires_valid_provenance_and_fails_closed_at_cap():
    version_a = _retained_version("accepted-a")
    version_c = _retained_version("accepted-c")
    assert _retained_company_project_history_is_safe(
        [version_c, version_a],
        source_id="retained-company-project-evaluation",
        schema_version="retained-company-project-v2",
    )
    malformed = _retained_version("malformed")
    malformed.provenance = {}
    assert not _retained_company_project_history_is_safe(
        [version_c, malformed],
        source_id="retained-company-project-evaluation",
        schema_version="retained-company-project-v2",
    )
    assert not _retained_company_project_history_is_safe(
        [version_c] * 65,
        source_id="retained-company-project-evaluation",
        schema_version="retained-company-project-v2",
    )


def test_native_history_reparses_nonempty_publication_date_metadata():
    metadata_version = _retained_version("accepted-with-metadata", metadata=True)
    assert metadata_version.provenance["retained_company_project"]["publication_date_metadata"]
    assert _retained_company_project_history_is_safe(
        [metadata_version],
        source_id="retained-company-project-evaluation",
        schema_version="retained-company-project-v2",
    )


@pytest.mark.parametrize("mismatch", ["hash", "url"])
def test_prior_run_source_receipt_requires_exact_immutable_source_binding(mismatch):
    prior = SimpleNamespace(
        id="claim-a",
        project_id="project-a",
        entity_key="company-a",
        person_name=None,
        organization="DataBank",
        category="owner_developer",
        organization_relationship="DIRECT",
        person_organization_relationship="UNKNOWN",
        person_project_relationship="UNKNOWN",
    )
    current = SimpleNamespace(**prior.__dict__)
    link = SimpleNamespace(
        entity_type="company",
        basis="project_scoped",
        state="current",
        source_evidence_id="evidence-a",
        source_version_hash="hash-a",
    )
    prior_source = SimpleNamespace(
        id="evidence-a",
        project_id="project-a",
        url="https://owner.example/site",
        content_hash="hash-a",
    )
    prior_citation = {
        "evidence_id": "evidence-a",
        "url": "https://owner.example/site",
        "quote": "DataBank develops the site with 480 MW.",
        "supports": "project_organization",
    }
    current_citations = [
        {
            "url": "https://owner.example/site",
            "quote": "DataBank develops the site with 640 MW.",
            "supports": "project_organization",
        }
    ]
    if mismatch == "hash":
        link.source_version_hash = "wrong-hash"
    else:
        prior_citation["url"] = "https://other.example/site"
    assert not _same_prior_run_project_scoped_company_role_revision(
        prior,
        current,
        link,
        prior_claim_ids={"claim-a"},
        prior_source=prior_source,
        prior_citation=prior_citation,
        current_citations=current_citations,
    )
