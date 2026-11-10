"""Add explicit synthetic, evidence-backed resolved accounts to a test corpus."""

from __future__ import annotations

from datetime import UTC, datetime
from hashlib import sha256
from uuid import UUID, uuid4
import json

from sqlalchemy import text
from sqlalchemy.orm import sessionmaker


def seed_resolved_operator_accounts(engine, manifest: dict) -> dict[str, str | bool]:
    """Qualify the 48-project synthetic operator cohort for account journeys.

    The fixture uses a fabricated but stable account identity and project-scoped
    source excerpts describing qualifying electrical construction activity.
    Every modified browse row remains labeled synthetic.
    """
    target = manifest["groups"]["de_central"]
    identity_id = uuid4()
    synthetic_contact_project = target["project_ids"][0]
    now = datetime.now(UTC)
    contact_evidence_id = None
    contact_project_id = None
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO company_identities (id, rrc_operator_number) VALUES (:id, :operator_number)"
            ),
            {"id": identity_id, "operator_number": target["operator_number"]},
        )
        projects = (
            connection.execute(
                text("""
                SELECT br.need_id, br.project_id, br.compact, br.summary,
                       e.id AS evidence_id, e.observation_id, o.source_id
                FROM browse_rows br
                JOIN need_observations no ON no.need_id=br.need_id
                JOIN evidence e ON e.observation_id=no.observation_id
                JOIN observations o ON o.id=e.observation_id
                WHERE br.generation_id=CAST(:generation AS uuid)
                  AND br.project_id=ANY(CAST(:project_ids AS uuid[]))
                ORDER BY br.project_id, e.id
            """),
                {
                    "generation": manifest["generation_id"],
                    "project_ids": target["project_ids"],
                },
            )
            .mappings()
            .all()
        )
        seen_projects: set[str] = set()
        for row in projects:
            project_id = str(row["project_id"])
            if project_id in seen_projects:
                continue
            seen_projects.add(project_id)
            excerpt = (
                f"Synthetic integration-test source. Project: {row['compact']['browse_title']}. "
                "Scope: new construction of compressor station and electrical service."
            )
            if project_id == str(synthetic_contact_project):
                excerpt += (
                    f" Synthetic fixture owner/operator: {target['name']}; "
                    f"RRC operator number {target['operator_number']}."
                )
                contact_evidence_id = row["evidence_id"]
                contact_project_id = row["project_id"]
            connection.execute(
                text("UPDATE evidence SET abstract=:abstract WHERE id=:id"),
                {"abstract": excerpt, "id": row["evidence_id"]},
            )
            connection.execute(
                text("""
                    UPDATE browse_rows
                    SET summary = summary || jsonb_build_object(
                      'synthetic_fixture', true,
                      'evidence', jsonb_build_array(jsonb_build_object(
                        'id', CAST(:evidence_id AS text), 'source_id', CAST(:source_id AS text),
                        'assessment_current', true)))
                    WHERE generation_id=CAST(:generation AS uuid) AND need_id=:need_id
                """),
                {
                    "evidence_id": str(row["evidence_id"]),
                    "source_id": row["source_id"],
                    "generation": manifest["generation_id"],
                    "need_id": row["need_id"],
                },
            )
            connection.execute(
                text("""
                    INSERT INTO browse_customer_memberships
                    (generation_id, company_identity_id, project_id, organization_name,
                     role, supporting_evidence_count, last_evidence_update)
                    VALUES (CAST(:generation AS uuid), :identity, :project,
                            'DE CENTRAL Synthetic Operator', 'asset_operator', 1, :updated)
                """),
                {
                    "generation": manifest["generation_id"],
                    "identity": identity_id,
                    "project": row["project_id"],
                    "updated": now,
                },
            )
        if len(seen_projects) != len(target["project_ids"]):
            raise RuntimeError(
                "Synthetic account fixture could not resolve every target project source."
            )
        malformed_contact_rows = connection.execute(
            text("""
                SELECT count(*)
                FROM browse_rows br
                CROSS JOIN LATERAL (
                  SELECT br.compact->'contact_actions' AS actions,
                         br.compact->'contact_people' AS people
                ) payload
                WHERE br.generation_id=CAST(:generation AS uuid)
                  AND (
                    (br.compact ? 'contact_actions' AND (
                      jsonb_typeof(payload.actions) <> 'array'
                      OR EXISTS (
                        SELECT 1 FROM jsonb_array_elements(
                          CASE WHEN jsonb_typeof(payload.actions)='array'
                            THEN payload.actions ELSE '[]'::jsonb END
                        ) AS action_item(value)
                        WHERE jsonb_typeof(action_item.value) <> 'object'
                      )
                    ))
                    OR (br.compact ? 'contact_people' AND (
                      jsonb_typeof(payload.people) <> 'array'
                      OR EXISTS (
                        SELECT 1 FROM jsonb_array_elements(
                          CASE WHEN jsonb_typeof(payload.people)='array'
                            THEN payload.people ELSE '[]'::jsonb END
                        ) AS person_item(value)
                        WHERE jsonb_typeof(person_item.value) <> 'object'
                      )
                    ))
                  )
            """),
            {"generation": manifest["generation_id"]},
        ).scalar_one()
        if malformed_contact_rows:
            raise RuntimeError(
                "Synthetic account fixture contact_actions/contact_people must be arrays of objects."
            )
        connection.execute(
            text("""
                UPDATE browse_generations
                SET input_revision=(SELECT input_revision FROM browse_state WHERE id=1)
                WHERE id=CAST(:generation AS uuid)
            """),
            {"generation": manifest["generation_id"]},
        )
    if contact_evidence_id is None or contact_project_id is None:
        raise RuntimeError("Synthetic contact project has no retained source evidence.")
    return _seed_native_contact_route(
        engine,
        manifest,
        identity_id=identity_id,
        project_id=contact_project_id,
        evidence_id=contact_evidence_id,
    )


def _seed_native_contact_route(
    engine, manifest, *, identity_id, project_id, evidence_id
):
    """Produce one synthetic phone route through the current native RRC pipeline."""
    from datetime import timedelta

    import gridlens.ingestion.adapters.pursuit_acquisition as acquisition
    import gridlens.intelligence.company_contact_discovery as discovery
    from gridlens.intelligence.company_contacts import company_contacts
    from gridlens.intelligence.project_contact_actions import project_contact_actions
    from gridlens.persistence.models import (
        CompanyProjectMembership,
        Evidence,
        Job,
        LogicalCall,
        LogicalCallBudget,
        Project,
    )
    from gridlens.settings import settings

    factory = sessionmaker(bind=engine, expire_on_commit=False)
    now = datetime.now(UTC)
    target = manifest["groups"]["de_central"]
    operator_number = target["operator_number"]
    organization = target["name"]
    with factory.begin() as session:
        project = session.get(Project, project_id)
        evidence = session.get(Evidence, evidence_id)
        if project is None or evidence is None:
            raise RuntimeError(
                "Synthetic contact project/evidence disappeared before native discovery."
            )
        evidence.abstract = (
            "Synthetic integration-test source. "
            f"{organization} is the synthetic owner/operator; "
            f"RRC operator number {operator_number}. "
            "No actual facility or contact is represented."
        )
        session.add(
            CompanyProjectMembership(
                company_identity_id=identity_id,
                project_id=project.id,
                role="asset_operator",
                organization_name=organization,
                source_id=project.source_id,
                source_evidence_id=evidence.id,
                source_version_hash=evidence.content_hash,
                decision_basis="synthetic_acceptance_fixture_current_source",
                operator_number=operator_number,
                state="current",
            )
        )
        queued = discovery.discover_company_contacts(session, identity_id, now=now)
        if queued.get("status") != "queued" or not queued.get("job_id"):
            raise RuntimeError(
                "Synthetic native contact producer did not enqueue its durable job."
            )
        job = session.get(Job, UUID(queued["job_id"]))
        if job is None:
            raise RuntimeError("Synthetic native contact job was not persisted.")
        job.status = "running"
        job.lease_owner = "synthetic-browser-fixture"
        job.fence = 1
        job.lease_until = now + timedelta(minutes=5)
        job_id = job.id

    snapshot = {
        "index_url": "https://www.rrc.texas.gov/oil-and-gas/research-and-statistics/operator-information/oil-gas-directory-operator-contact/",
        "source_url": "https://www.rrc.texas.gov/media/synthetic/oil-and-gas-directory-11-08-26.xlsx",
        "filename_date": now.date().isoformat(),
        "workbook_header_timestamp": now.strftime("%m/%d/%Y 12:00:00 PM"),
        "workbook_header_date": now.date().isoformat(),
        "landing_freshness_statement": "Synthetic fixture; no external workbook was retrieved.",
        "observed_at": now.isoformat(),
        "raw_sha256": sha256(
            b"synthetic RRC P5 browser fixture; no external retrieval"
        ).hexdigest(),
        "synthetic_fixture": True,
        "operators": {
            operator_number: [
                {
                    "operator_number": operator_number,
                    "organization": organization,
                    "country": "USA",
                    "normal_phone": "7135550101",
                    "status": "Active",
                    "row_number": 1857,
                }
            ]
        },
    }
    original_session_local = discovery.SessionLocal
    original_loader = discovery.load_current_directory
    original_search = acquisition.discover_urls
    original_enabled = settings.intelligence_enabled
    try:
        discovery.SessionLocal = factory
        discovery.load_current_directory = lambda **_kwargs: snapshot
        acquisition.discover_urls = lambda *_args, **_kwargs: (_ for _ in ()).throw(
            RuntimeError("Paid search must remain disabled in this synthetic seed.")
        )
        settings.intelligence_enabled = False
        outcome = discovery.process_company_contact_discovery(
            job_id, "synthetic-browser-fixture", 1, now=now
        )
    finally:
        discovery.SessionLocal = original_session_local
        discovery.load_current_directory = original_loader
        acquisition.discover_urls = original_search
        settings.intelligence_enabled = original_enabled

    with factory.begin() as session:
        if (
            session.query(LogicalCall).count()
            or session.query(LogicalCallBudget).count()
        ):
            raise RuntimeError(
                "Synthetic fixture unexpectedly created paid-call ledger rows."
            )
        projection = company_contacts(session, identity_id)
        actions = project_contact_actions(
            {
                "contacts": [
                    contact.model_dump(mode="json") for contact in projection.contacts
                ]
            }
        )
        if (
            outcome.get("results", [{}])[0].get("reason")
            != "generic_public_methods_persisted"
        ):
            raise RuntimeError(
                "Native fixture did not persist the exact P5 company phone method."
            )
        if len(actions) != 1 or actions[0].get("kind") != "call":
            raise RuntimeError(
                "Native fixture did not produce exactly one source-backed phone route."
            )
        actions[0]["synthetic_fixture"] = True
        session.execute(
            text("""
                UPDATE browse_rows SET compact = compact || jsonb_build_object(
                  'contact_actions', CAST(:contact AS jsonb))
                WHERE generation_id=CAST(:generation AS uuid)
                  AND project_id=CAST(:project AS uuid)
            """),
            {
                "contact": json.dumps(actions),
                "generation": manifest["generation_id"],
                "project": project_id,
            },
        )
    with engine.begin() as connection:
        connection.execute(
            text("""
                UPDATE browse_generations
                SET input_revision=(SELECT input_revision FROM browse_state WHERE id=1)
                WHERE id=CAST(:generation AS uuid)
            """),
            {"generation": manifest["generation_id"]},
        )
    return {
        "company": organization,
        "phone_href": actions[0]["href"],
        "synthetic_fixture": True,
    }
