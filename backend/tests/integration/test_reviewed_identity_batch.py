from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from db_reset import reset_test_database
from sqlalchemy import create_engine, select
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from gridlens.intelligence.reviewed_identity_batch import BatchRejected, execute_batch
from gridlens.persistence.models import (
    BuyingChainClaim,
    BuyingChainEvidence,
    BuyingChainIdentityLink,
    BuyingChainRun,
    CompanyIdentity,
    PowerNeed,
    Project,
    Source,
)
from gridlens.settings import settings

NOW = datetime(2026, 10, 24, 12, tzinfo=UTC)


@pytest.fixture
def f_db():
    target = make_url(settings.test_database_url)
    application = make_url(settings.database_url)
    assert target.database and target.database.endswith("_test")
    assert target != application
    engine = create_engine(settings.test_database_url)
    reset_test_database(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    with factory.begin() as session:
        session.add(
            Source(
                id="f-review-test",
                publisher="Synthetic identity batch tests",
                endpoint="https://example.test/identity",
                family="news",
                geography="US",
                industries=[],
                retrieval_method="test",
                health={},
            )
        )
    yield factory
    engine.dispose()


def _seed_claim(session, key: str, project_name: str, role: str = "owner"):
    project = Project(
        source_id="f-review-test",
        external_id=key,
        name=project_name,
        location="Austin, TX",
        identity_key=key,
        identity_facts={},
    )
    session.add(project)
    session.flush()
    session.add(
        PowerNeed(
            project_id=project.id,
            activity_key="construction",
            tier="Signal",
            rationale="Synthetic fixture",
        )
    )
    organization = "Amazon Data Services, Inc"
    quote = (
        f"{organization} is the general contractor for {project_name}."
        if role == "contractor"
        else f"{organization} is named on synthetic project {key}."
    )
    evidence = BuyingChainEvidence(
        project_id=project.id,
        url=f"https://example.test/relationships/{key}",
        title="Synthetic relationship record",
        excerpt=quote,
        content_hash=uuid4().hex,
        extraction_location="Synthetic fixture",
        observed_at=NOW,
        last_seen_at=NOW,
        project_match_reason="Synthetic, isolated test data.",
    )
    session.add(evidence)
    session.flush()
    claim = BuyingChainClaim(
        project_id=project.id,
        entity_key=f"{key}-{organization}",
        fingerprint=uuid4().hex,
        policy_version="synthetic-fixture-v1",
        organization=organization,
        person_name=None,
        title=None,
        category="contractor" if role == "contractor" else "owner_developer",
        organization_relationship="DIRECT",
        person_organization_relationship="UNKNOWN",
        person_project_relationship="DIRECT",
        evidence_strength="High",
        reason="Synthetic owner/participant statement.",
        citations=[
            {
                "evidence_id": str(evidence.id),
                "url": evidence.url,
                "quote": quote,
                "supports": "project_organization",
            }
        ],
        public_contacts=[],
        observed_at=NOW,
    )
    session.add(claim)
    session.flush()
    session.add(
        BuyingChainRun(
            project_id=project.id,
            input_hash=uuid4().hex,
            evidence_ids=[str(evidence.id)],
            claim_ids=[str(claim.id)],
            policy_version="synthetic-fixture-v1",
            status="complete",
            documents_checked=1,
            candidates_added=1,
            unresolved=[],
        )
    )
    identity = CompanyIdentity()
    session.add(identity)
    session.flush()
    link = BuyingChainIdentityLink(
        claim_id=claim.id,
        entity_type="company",
        company_identity_id=identity.id,
        reason="Stable project-scoped claim identity; no cross-project merge inferred.",
        basis="project_scoped",
        source_evidence_id=evidence.id,
        source_version_hash=evidence.content_hash,
        state="current",
    )
    session.add(link)
    session.flush()
    return project, claim, link


def _evidence_for(session, link):
    evidence = session.get(BuyingChainEvidence, link.source_evidence_id)
    assert evidence is not None
    return evidence


def _bound_manifest(session, anchor, selected):
    # Keep this helper explicit so each manifest row is joined from the exact
    # claim/link/evidence IDs created by the synthetic scenario.
    anchor_project, anchor_claim, anchor_link = anchor
    anchor_evidence = _evidence_for(session, anchor_link)
    target_id = anchor_link.company_identity_id
    rows = []
    for project, claim, link in selected:
        evidence = _evidence_for(session, link)
        rows.append(
            {
                "claim_id": str(claim.id),
                "project_id": str(project.id),
                "entity_type": "company",
                "current_link_id": str(link.id),
                "current_identity_id": str(link.company_identity_id),
                "evidence_id": str(evidence.id),
                "evidence_hash": evidence.content_hash,
                "target_identity_id": str(target_id),
                "reviewed_by": "synthetic-reviewer",
                "reason": "Synthetic explicit evidence review selects the same company identity.",
            }
        )
    return {
        "operation": "map",
        "batch_id": "synthetic-owner-review-1",
        "target": {
            "company_identity_id": str(target_id),
            "claim_id": str(anchor_claim.id),
            "project_id": str(anchor_project.id),
            "link_id": str(anchor_link.id),
            "evidence_id": str(anchor_evidence.id),
            "evidence_hash": anchor_evidence.content_hash,
        },
        "items": rows,
    }


def test_exact_reviewed_mapping_is_scoped_idempotent_and_reversible(f_db):
    with f_db.begin() as session:
        a = _seed_claim(session, "a", "Campus A Data Center")
        b = _seed_claim(session, "b", "Campus B Data Center")
        c = _seed_claim(session, "c", "Campus C Data Center")
        unrelated = _seed_claim(session, "unrelated", "Remote County Data Center")
        contractor = _seed_claim(session, "contractor", "Contractor Campus", "contractor")
        manifest = _bound_manifest(session, a, [a, b, c])
        untouched = {
            "unrelated": (unrelated[1].id, unrelated[2].id, unrelated[2].company_identity_id),
            "contractor": (contractor[1].id, contractor[2].id, contractor[2].company_identity_id),
        }

        bad_hash = {
            **manifest,
            "items": [{**manifest["items"][1], "evidence_hash": "0" * 64}],
        }
        with pytest.raises(BatchRejected, match="hash changed"):
            execute_batch(session, bad_hash)
        changed_link = {
            **manifest,
            "items": [{**manifest["items"][1], "current_link_id": str(uuid4())}],
        }
        with pytest.raises(BatchRejected, match="current link or identity changed"):
            execute_batch(session, changed_link)

        preview = execute_batch(session, manifest)
        assert preview["mode"] == "dry_run"
        assert len(preview["items"]) == 3
        assert len({row["project_id"] for row in preview["items"]}) == 3
        assert preview["items"][0]["replayed"]  # selected identity anchor is already the target
        changed_review = {
            **manifest,
            "items": [
                *manifest["items"][:1],
                {
                    **manifest["items"][1],
                    "reviewed_by": "different-reviewer",
                    "reason": "Changed after preview.",
                },
                *manifest["items"][2:],
            ],
        }
        with pytest.raises(BatchRejected, match="digest differs"):
            execute_batch(
                session,
                changed_review,
                apply=True,
                expected_digest=preview["digest"],
            )
        applied = execute_batch(session, manifest, apply=True, expected_digest=preview["digest"])
        assert applied["mode"] == "applied"
        assert len(applied["results"]) == 3
        # Replay the identical reviewed map. It produces no extra link rows.
        current_links = {
            row.claim_id: row
            for row in session.scalars(
                select(BuyingChainIdentityLink).where(BuyingChainIdentityLink.state == "current")
            ).all()
        }
        for item in manifest["items"]:
            old_id = item["current_link_id"]
            current = current_links[UUID(item["claim_id"])]
            if old_id != str(current.id):
                assert session.get(BuyingChainIdentityLink, UUID(old_id)).state == "superseded"
            assert current.company_identity_id == UUID(item["target_identity_id"])
        replay_preview = execute_batch(session, manifest)
        replay = execute_batch(
            session, manifest, apply=True, expected_digest=replay_preview["digest"]
        )
        assert all(row["replayed"] for row in replay["results"])
        for claim_id, old_link_id, old_identity in untouched.values():
            assert current_links[claim_id].id == old_link_id
            assert current_links[claim_id].company_identity_id == old_identity
        # Build an inverse review that restores B/C's exact superseded links.
        rollback_items = []
        for item in manifest["items"][1:]:
            old_link = session.get(BuyingChainIdentityLink, UUID(item["current_link_id"]))
            mapped_link = session.scalar(
                select(BuyingChainIdentityLink).where(
                    BuyingChainIdentityLink.claim_id == UUID(item["claim_id"]),
                    BuyingChainIdentityLink.state == "current",
                )
            )
            rollback_items.append(
                {
                    **item,
                    "current_link_id": str(mapped_link.id),
                    "current_identity_id": str(mapped_link.company_identity_id),
                    "target_identity_id": str(old_link.company_identity_id),
                    "restore_link_id": str(old_link.id),
                    "reviewed_by": "synthetic-reviewer",
                    "reason": "Synthetic inverse review restores the recorded prior identity link.",
                }
            )
        rollback_manifest = {
            "operation": "rollback",
            "batch_id": "synthetic-owner-review-1-inverse",
            "items": rollback_items,
        }
        preview = execute_batch(session, rollback_manifest)
        first_restore = session.get(
            BuyingChainIdentityLink, UUID(rollback_items[0]["restore_link_id"])
        )
        alternate_restore = BuyingChainIdentityLink(
            claim_id=first_restore.claim_id,
            entity_type="company",
            company_identity_id=first_restore.company_identity_id,
            reason="Alternate synthetic superseded history row.",
            basis="project_scoped",
            source_evidence_id=first_restore.source_evidence_id,
            source_version_hash=first_restore.source_version_hash,
            state="superseded",
        )
        session.add(alternate_restore)
        session.flush()
        changed_anchor = {
            **rollback_manifest,
            "items": [
                {
                    **rollback_items[0],
                    "restore_link_id": str(alternate_restore.id),
                },
                *rollback_items[1:],
            ],
        }
        with pytest.raises(BatchRejected, match="digest differs"):
            execute_batch(
                session,
                changed_anchor,
                apply=True,
                expected_digest=preview["digest"],
            )
        applied = execute_batch(
            session, rollback_manifest, apply=True, expected_digest=preview["digest"]
        )
        assert applied["mode"] == "applied"
        inverse_replay_preview = execute_batch(session, rollback_manifest)
        inverse_replay = execute_batch(
            session,
            rollback_manifest,
            apply=True,
            expected_digest=inverse_replay_preview["digest"],
        )
        assert all(row["replayed"] for row in inverse_replay["results"])
        for item in rollback_manifest["items"]:
            restored = session.scalar(
                select(BuyingChainIdentityLink).where(
                    BuyingChainIdentityLink.claim_id == UUID(item["claim_id"]),
                    BuyingChainIdentityLink.state == "current",
                )
            )
            assert restored is not None
            assert restored.company_identity_id == UUID(item["target_identity_id"])
            assert (
                session.get(BuyingChainIdentityLink, UUID(item["current_link_id"])).state
                == "superseded"
            )
