"""Safe retained-data recovery staging and guarded publication."""

import ast
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete, select, update
from test_saved_browse import seed

from gridlens.intelligence.saved_browse import (
    current_generation,
    inspect_recovery_stage,
    publish_recovery_stage,
    rebuild,
    stage_recovery,
)
from gridlens.persistence import browse_invalidation
from gridlens.persistence.models import (
    BrowseCustomerMembership,
    BrowseDirtyProject,
    BrowseGeneration,
    BrowseRecoveryStage,
    BrowseRow,
    BrowseState,
    BrowseUnresolvedCustomer,
    BuyingChainClaim,
    BuyingChainEvidence,
    BuyingChainIdentityLink,
    CompanyIdentity,
    Project,
)

pytest_plugins = ["test_saved_browse"]


def _ready_stage(factory):
    seed(factory, count=2)
    assert rebuild(factory)["status"] == "published"
    with factory() as session:
        return current_generation(session)


def test_recovery_stage_is_invisible_and_keeps_dirty_journal(saved_db):
    original = _ready_stage(saved_db)
    dirty_id = UUID("00000000-0000-0000-0000-000000000123")
    with saved_db.begin() as session:
        session.add(BrowseDirtyProject(project_id=dirty_id, revision=1))
        state = session.get(BrowseState, 1)
        original_pointer = state.generation_id
        original_prepared = state.prepared_generation_id
        original_revision = state.input_revision
        original_full_revision = state.full_revision

    result = stage_recovery(saved_db)
    assert result["status"] == "staged"
    assert result["published"] is False
    staged_id = UUID(result["generation_id"])
    with saved_db() as session:
        state = session.get(BrowseState, 1)
        assert state.generation_id == original_pointer == original.id
        assert state.prepared_generation_id == original_prepared
        assert state.input_revision == original_revision
        assert state.full_revision == original_full_revision
        assert session.get(BrowseDirtyProject, dirty_id) is not None
        assert session.get(BrowseRecoveryStage, staged_id) is not None
    assert inspect_recovery_stage(saved_db, staged_id)["status"] == "ready"


def test_publish_cas_clears_prepared_and_retains_displaced_generation(saved_db):
    original = _ready_stage(saved_db)
    prepared = rebuild(saved_db, _prepare_at=original.valid_until)
    assert prepared["status"] == "prepared"
    prepared_id = UUID(prepared["generation_id"])

    staged = stage_recovery(saved_db)
    staged_id = UUID(staged["generation_id"])
    receipt = inspect_recovery_stage(saved_db, staged_id)
    assert receipt["status"] == "ready"
    assert UUID(receipt["expected_state"]["prepared_generation_id"]) == prepared_id

    result = publish_recovery_stage(saved_db, staged_id)
    assert result["status"] == "published"
    assert result["displaced_generation_id"] == str(original.id)
    with saved_db() as session:
        state = session.get(BrowseState, 1)
        assert state.generation_id == staged_id
        assert state.prepared_generation_id is None
        assert session.get(BrowseGeneration, original.id) is not None
        assert session.get(BrowseGeneration, prepared_id) is not None
    assert publish_recovery_stage(saved_db, staged_id)["status"] == "already_published"


def test_publish_obeys_shared_build_lock_and_can_retry_after_release(saved_db):
    from sqlalchemy import func

    from gridlens.intelligence import saved_browse

    original = _ready_stage(saved_db)
    staged_id = UUID(stage_recovery(saved_db)["generation_id"])
    with saved_db() as lock_session:
        lock_session.scalar(select(func.pg_advisory_lock(saved_browse.BUILD_LOCK)))
        assert publish_recovery_stage(saved_db, staged_id)["status"] == "busy"
        lock_session.scalar(select(func.pg_advisory_unlock(saved_browse.BUILD_LOCK)))
    with saved_db() as session:
        assert session.get(BrowseState, 1).generation_id == original.id
    assert publish_recovery_stage(saved_db, staged_id)["status"] == "published"


@pytest.mark.parametrize("target", ["browse_row", "membership", "unresolved"])
def test_publish_rejects_same_count_or_child_table_integrity_drift(saved_db, monkeypatch, target):
    from gridlens.intelligence import saved_browse

    _ready_stage(saved_db)
    with saved_db.begin() as session:
        source_row = session.scalar(select(BrowseRow))
        project_id = source_row.project_id
        identity = CompanyIdentity()
        session.add(identity)
        session.flush()
        identity_id = identity.id
    if target in {"membership", "unresolved"}:
        original_projection = saved_browse._write_customer_projection

        def add_child_rows(session, generation_id):
            original_projection(session, generation_id)
            if target == "membership":
                session.add(
                    BrowseCustomerMembership(
                        generation_id=generation_id,
                        company_identity_id=identity_id,
                        project_id=project_id,
                        organization_name="Synthetic test company",
                        role="owner",
                        supporting_evidence_count=1,
                    )
                )
            else:
                session.add(
                    BrowseUnresolvedCustomer(
                        generation_id=generation_id,
                        project_id=project_id,
                        organization_name="Synthetic unresolved company",
                        role="owner",
                        reason="test integrity fixture",
                    )
                )

        monkeypatch.setattr(saved_browse, "_write_customer_projection", add_child_rows)
    staged = stage_recovery(saved_db)
    staged_id = UUID(staged["generation_id"])
    with saved_db.begin() as session:
        if target == "browse_row":
            row = session.scalar(select(BrowseRow).where(BrowseRow.generation_id == staged_id))
            row.summary = {**row.summary, "integrity_probe": "changed"}
        elif target == "membership":
            session.execute(
                delete(BrowseCustomerMembership).where(
                    BrowseCustomerMembership.generation_id == staged_id
                )
            )
        else:
            session.execute(
                delete(BrowseUnresolvedCustomer).where(
                    BrowseUnresolvedCustomer.generation_id == staged_id
                )
            )
    assert inspect_recovery_stage(saved_db, staged_id)["status"] == "stale_or_invalid"
    assert publish_recovery_stage(saved_db, staged_id)["status"] == "candidate_invalid"


@pytest.mark.parametrize(
    "corruption", ["policy", "expiry", "extended", "built_at", "row", "receipt", "revision"]
)
def test_already_published_retry_revalidates_receipt_and_candidate(saved_db, corruption):
    _ready_stage(saved_db)
    staged = stage_recovery(saved_db)
    staged_id = UUID(staged["generation_id"])
    assert publish_recovery_stage(saved_db, staged_id)["status"] == "published"
    with saved_db.begin() as session:
        generation = session.get(BrowseGeneration, staged_id)
        receipt = session.get(BrowseRecoveryStage, staged_id)
        if corruption == "policy":
            generation.policy_version = "stale-runtime"
        elif corruption == "expiry":
            from datetime import timedelta

            generation.valid_until -= timedelta(days=1)
        elif corruption == "extended":
            from datetime import timedelta

            generation.valid_until += timedelta(days=1)
        elif corruption == "built_at":
            from datetime import timedelta

            generation.built_at += timedelta(days=1)
        elif corruption == "row":
            row = session.scalar(select(BrowseRow).where(BrowseRow.generation_id == staged_id))
            row.summary = {**row.summary, "retry_probe": "changed"}
        elif corruption == "receipt":
            receipt.integrity_digest = "0" * 64
        else:
            state = session.get(BrowseState, 1)
            state.input_revision += 1
    result = publish_recovery_stage(saved_db, staged_id)
    assert result["status"] == ("state_drift" if corruption == "revision" else "candidate_invalid")


def test_validity_horizon_is_resampled_after_integrity_scan(saved_db, monkeypatch):
    from datetime import UTC, datetime, timedelta

    from gridlens.intelligence import saved_browse

    _ready_stage(saved_db)
    staged_id = UUID(stage_recovery(saved_db)["generation_id"])
    with saved_db.begin() as session:
        generation = session.get(BrowseGeneration, staged_id)
        receipt = session.get(BrowseRecoveryStage, staged_id)
        generation.valid_until = datetime.now(UTC) + timedelta(seconds=90)
        session.flush()
        receipt.integrity_digest, counts = saved_browse._recovery_integrity_digest(
            session, generation
        )
        receipt.row_count = counts[BrowseRow.__tablename__]
        receipt.membership_count = counts[BrowseCustomerMembership.__tablename__]
        receipt.unresolved_count = counts[BrowseUnresolvedCustomer.__tablename__]
        deadline = generation.valid_until

    clock = {"now": deadline - timedelta(seconds=90)}

    class AdvancingClock(datetime):
        @classmethod
        def now(cls, tz=None):
            return clock["now"]

    original_digest = saved_browse._recovery_integrity_digest

    def advances_past_minimum(session, generation):
        result = original_digest(session, generation)
        clock["now"] = deadline - timedelta(seconds=30)
        return result

    monkeypatch.setattr(saved_browse, "datetime", AdvancingClock)
    monkeypatch.setattr(saved_browse, "_recovery_integrity_digest", advances_past_minimum)
    assert inspect_recovery_stage(saved_db, staged_id)["status"] == "stale_or_invalid"
    clock["now"] = deadline - timedelta(seconds=90)
    assert publish_recovery_stage(saved_db, staged_id)["status"] == "candidate_invalid"


def test_identity_link_installer_sql_matches_migration_0047(saved_db):
    migration_path = (
        Path(__file__).parents[2] / "migrations/versions/0047_scoped_identity_link_browse.py"
    )
    module = ast.parse(migration_path.read_text(encoding="utf-8"))
    source = next(
        ast.literal_eval(node.value)
        for node in module.body
        if isinstance(node, ast.Assign)
        and any(
            isinstance(target, ast.Name) and target.id == "IDENTITY_LINK_SQL"
            for target in node.targets
        )
    )
    assert browse_invalidation.IDENTITY_LINK_SQL == source


def test_identity_entity_installer_sql_matches_migration_0049(saved_db):
    migration_path = (
        Path(__file__).parents[2] / "migrations/versions/0049_scoped_identity_entity_browse.py"
    )
    module = ast.parse(migration_path.read_text(encoding="utf-8"))
    source = next(
        ast.literal_eval(node.value)
        for node in module.body
        if isinstance(node, ast.Assign)
        and any(
            isinstance(target, ast.Name) and target.id == "IDENTITY_ENTITY_SQL"
            for target in node.targets
        )
    )
    assert browse_invalidation.IDENTITY_ENTITY_SQL == source


def test_company_membership_installer_sql_matches_migration_0049(saved_db):
    migration_path = (
        Path(__file__).parents[2] / "migrations/versions/0049_scoped_identity_entity_browse.py"
    )
    module = ast.parse(migration_path.read_text(encoding="utf-8"))
    source = next(
        ast.literal_eval(node.value)
        for node in module.body
        if isinstance(node, ast.Assign)
        and any(
            isinstance(target, ast.Name) and target.id == "COMPANY_MEMBERSHIP_SCOPE_SQL"
            for target in node.targets
        )
    )
    assert browse_invalidation.COMPANY_MEMBERSHIP_SCOPE_SQL == source


def test_identity_link_installer_scopes_known_claim_invalidation(saved_db):
    from gridlens.persistence.models import BuyingChainRun

    seed(saved_db, count=1)
    with saved_db.begin() as session:
        project = session.scalar(select(Project))
        identity = CompanyIdentity()
        session.add(identity)
        source_evidence = BuyingChainEvidence(
            project_id=project.id,
            url="https://example.test/identity-link",
            title="Synthetic identity relationship",
            excerpt="Synthetic only.",
            content_hash="a" * 64,
            extraction_location="Synthetic fixture",
            observed_at=datetime.now(UTC),
            last_seen_at=datetime.now(UTC),
            project_match_reason="Synthetic test data.",
        )
        session.add(source_evidence)
        session.flush()
        claim = BuyingChainClaim(
            project_id=project.id,
            entity_key="synthetic-identity-link",
            fingerprint="b" * 64,
            policy_version="synthetic-test-v1",
            organization="Synthetic owner",
            person_name=None,
            title=None,
            category="owner_developer",
            organization_relationship="DIRECT",
            person_organization_relationship="UNKNOWN",
            person_project_relationship="DIRECT",
            evidence_strength="High",
            reason="Synthetic test fixture.",
            citations=[],
            public_contacts=[],
            observed_at=datetime.now(UTC),
        )
        session.add(claim)
        session.add(
            BuyingChainRun(
                project_id=project.id,
                input_hash="c" * 64,
                evidence_ids=[str(source_evidence.id)],
                claim_ids=[],
                policy_version="synthetic-test-v1",
                status="complete",
                documents_checked=1,
                candidates_added=1,
                unresolved=[],
            )
        )
        session.flush()
        link = BuyingChainIdentityLink(
            claim_id=claim.id,
            entity_type="company",
            company_identity_id=identity.id,
            reason="Synthetic link",
            basis="project_scoped",
            source_evidence_id=source_evidence.id,
            source_version_hash=source_evidence.content_hash,
            state="current",
        )
        session.add(link)
        session.flush()
        project_id, link_id = project.id, link.id
        state = session.get(BrowseState, 1)
        before_input, before_full = state.input_revision, state.full_revision
        session.execute(delete(BrowseDirtyProject))

    with saved_db.begin() as session:
        session.execute(
            update(BuyingChainIdentityLink)
            .where(BuyingChainIdentityLink.id == link_id)
            .values(state="superseded")
        )
    with saved_db() as session:
        state = session.get(BrowseState, 1)
        assert state.input_revision == before_input + 1
        assert state.full_revision == before_full
        assert session.get(BrowseDirtyProject, project_id) is not None


@pytest.mark.parametrize(
    "field", ["input_revision", "full_revision", "generation_id", "prepared_generation_id"]
)
def test_publish_rejects_each_state_drift(saved_db, field):
    _ready_stage(saved_db)
    staged = stage_recovery(saved_db)
    staged_id = UUID(staged["generation_id"])
    with saved_db.begin() as session:
        state = session.get(BrowseState, 1)
        if field.endswith("generation_id"):
            state.__setattr__(field, None if field == "generation_id" else uuid4())
        else:
            state.__setattr__(field, getattr(state, field) + 1)
    assert publish_recovery_stage(saved_db, staged_id)["status"] == "state_drift"


@pytest.mark.parametrize(
    "invalidity", ["policy", "digest", "future", "expired", "extended", "built_at", "rows"]
)
def test_publish_rejects_candidate_that_is_not_current_complete_and_fresh(saved_db, invalidity):
    _ready_stage(saved_db)
    staged = stage_recovery(saved_db)
    staged_id = UUID(staged["generation_id"])
    with saved_db.begin() as session:
        generation = session.get(BrowseGeneration, staged_id)
        if invalidity == "policy":
            generation.policy_version = "wrong-policy"
        elif invalidity == "digest":
            generation.digest = "0" * 64
        elif invalidity == "future":
            from datetime import timedelta

            generation.valid_from += timedelta(days=1)
        elif invalidity == "expired":
            from datetime import timedelta

            generation.valid_until -= timedelta(days=1)
        elif invalidity == "extended":
            from datetime import timedelta

            generation.valid_until += timedelta(days=1)
        elif invalidity == "built_at":
            from datetime import timedelta

            generation.built_at += timedelta(days=1)
        elif invalidity == "rows":
            generation.row_count += 1
    assert inspect_recovery_stage(saved_db, staged_id)["status"] == "stale_or_invalid"
    assert publish_recovery_stage(saved_db, staged_id)["status"] == "candidate_invalid"
    with saved_db() as session:
        assert session.get(BrowseState, 1).generation_id != staged_id
