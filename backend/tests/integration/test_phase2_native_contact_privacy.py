"""Current native operator contact projections remain suppressible after caching."""

from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import select

pytest_plugins = ["test_saved_browse"]


def test_native_rrc_contact_is_visible_then_immediately_suppressed_in_cached_reads(
    saved_db, monkeypatch
):
    from test_saved_browse import seed

    import gridlens.intelligence.company_contact_discovery as discovery
    from gridlens.domain.evaluation_clock import evaluate_at
    from gridlens.ingestion.adapters.buying_chain_public import PublicDocument
    from gridlens.intelligence.company_contacts import company_contacts
    from gridlens.intelligence.contact_suppressions import (
        method_suppression_key,
        record_contact_suppression,
    )
    from gridlens.intelligence.project_results import page as project_page
    from gridlens.intelligence.saved_browse import rebuild
    from gridlens.persistence.models import (
        CompanyIdentity,
        CompanyProjectMembership,
        Evidence,
        Job,
        Observation,
        PowerNeed,
        Project,
    )
    from gridlens.settings import settings

    process_at = datetime.now(UTC)
    need_ids = seed(saved_db, count=1, histories=1)
    with saved_db.begin() as session:
        project = session.scalar(select(Project).join(PowerNeed).where(PowerNeed.id == need_ids[0]))
        assert project is not None
        project.region_status = "ELIGIBLE"
        evidence = session.scalar(
            select(Evidence).join(Observation).where(Observation.external_id == "0-0")
        )
        assert evidence is not None
        observation = session.get(Observation, evidence.observation_id)
        assert observation is not None
        evidence.abstract = "Operator 123456: EOG Resources."
        evidence.title = "RRC operator 123456 drilling permit"
        observation.abstract = evidence.abstract
        observation.title = evidence.title
        identity = CompanyIdentity(rrc_operator_number="123456")
        session.add(identity)
        session.flush()
        session.add(
            CompanyProjectMembership(
                company_identity_id=identity.id,
                project_id=project.id,
                role="asset_operator",
                organization_name="EOG Resources",
                source_id=observation.source_id,
                source_evidence_id=evidence.id,
                source_version_hash=evidence.content_hash,
                decision_basis="typed_rrc_operator_number_v1",
                operator_number="123456",
                state="current",
            )
        )
        queued = discovery.discover_company_contacts(session, identity.id, now=process_at)
        job = session.get(Job, UUID(queued["job_id"]))
        assert job is not None
        job.status, job.lease_owner, job.fence = "running", "native-privacy-test", 1
        job.lease_until = datetime.now(UTC) + timedelta(minutes=5)
        job_id, company_id, project_id = job.id, identity.id, project.id

    registry_url = discovery._rrc_url("123456")
    assert registry_url is not None
    registry_text = (
        "Organization Operator Query Results\nOperator Number: 123456\n"
        "Operator Name: EOG Resources\nOrganization Phone No: (713) 651-7000\n"
        "Agency Phone: (512) 000-0000\nEmergency Phone: (713) 555-1212"
    )
    monkeypatch.setattr(discovery, "SessionLocal", saved_db)
    monkeypatch.setattr(settings, "intelligence_enabled", False)
    monkeypatch.setattr(
        discovery,
        "retrieve",
        lambda url, **_kwargs: PublicDocument(
            url, "RRC Operator Registry", registry_text, observed_at=process_at
        ),
    )
    result = discovery.process_company_contact_discovery(
        job_id, "native-privacy-test", 1, now=process_at
    )
    assert result["results"][0]["source_class"] == "public_registry"

    rebuild(saved_db)
    with saved_db.begin() as session:
        with evaluate_at(process_at + timedelta(minutes=1)):
            before = company_contacts(session, company_id)
            projected_before = project_page(
                session,
                project_ids=[project_id],
                include_signals=True,
                primary_customer_ids_by_project={str(project_id): str(company_id)},
            )
        native_values = {
            method["value"] for contact in before.contacts for method in contact.methods
        }
        assert native_values == {"(713) 651-7000"}, result["results"]
        assert projected_before["total"] == 1
        contact_before = projected_before["items"][0]["contact"]
        assert [action["href"] for action in contact_before] == ["tel:7136517000"]

        record_contact_suppression(
            session,
            scope="method",
            subject_key=method_suppression_key(company_id, None, "phone", "(713) 651-7000"),
            action="suppress",
            expected_version=0,
            reason="Deterministic privacy regression fixture.",
            actor="test",
            idempotency_key="phase2-native-method-suppression",
        )
        with evaluate_at(process_at + timedelta(minutes=1)):
            after = company_contacts(session, company_id)
            projected_after = project_page(
                session,
                project_ids=[project_id],
                include_signals=True,
                primary_customer_ids_by_project={str(project_id): str(company_id)},
            )
        assert not any(
            method["value"] == "(713) 651-7000"
            for contact in after.contacts
            for method in contact.methods
        )
        assert projected_after["total"] == 1
        assert projected_after["items"][0]["contact"] == []
        serialized = repr(projected_after["items"])
        assert "(713) 651-7000" not in serialized
        assert "7136517000" not in serialized
