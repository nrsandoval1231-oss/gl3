"""Add explicit synthetic, evidence-backed resolved accounts to a test corpus."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4
from hashlib import sha256
import json

from sqlalchemy import text


def seed_resolved_operator_accounts(engine, manifest: dict) -> None:
    """Qualify the 48-project synthetic operator cohort for account journeys.

    The fixture uses a fabricated but stable account identity and project-scoped
    source excerpts describing qualifying electrical construction activity.
    Every modified browse row remains labeled synthetic.
    """
    target = manifest["groups"]["de_central"]
    identity_id = uuid4()
    synthetic_contact_project = target["project_ids"][0]
    now = datetime.now(timezone.utc)
    with engine.begin() as connection:
        connection.execute(
            text("INSERT INTO company_identities (id, rrc_operator_number) VALUES (:id, :operator_number)"),
            {"id": identity_id, "operator_number": target["operator_number"]},
        )
        projects = connection.execute(
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
            {"generation": manifest["generation_id"], "project_ids": target["project_ids"]},
        ).mappings().all()
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
                {"evidence_id": str(row["evidence_id"]), "source_id": row["source_id"],
                 "generation": manifest["generation_id"], "need_id": row["need_id"]},
            )
            if project_id == synthetic_contact_project:
                # Explicitly synthetic, source-backed contact methods exercise
                # the normal privacy-filtered contact path without contacting
                # a real person or domain. The reserved .invalid address and
                # 555 number are safe to inspect in the browser only.
                source_url = "https://example.invalid/synthetic-contact"
                quote = (
                    "Synthetic integration-test source: DE CENTRAL Synthetic Operator "
                    "project contact is buyer@example.invalid or +15555550101."
                )
                evidence_key = sha256(quote.encode()).hexdigest()
                buying_evidence_id = uuid4()
                claim_id = uuid4()
                run_id = uuid4()
                contact_actions = [
                    {
                        "kind": kind,
                        "href": href,
                        "company": "DE CENTRAL Synthetic Operator",
                        "name": "Synthetic Buyer",
                        "title": "Project Contact",
                        "responsibility": "Verified project responsibility",
                        "purchasing_authority": "Synthetic test contact; authority requires confirmation",
                        "source_url": source_url,
                        "company_identity_id": str(identity_id),
                        "claim_id": str(claim_id),
                        "synthetic_fixture": True,
                    }
                    for kind, href in (
                        ("email", "mailto:buyer@example.invalid"),
                        ("call", "tel:+15555550101"),
                    )
                ]
                connection.execute(
                    text("""
                        INSERT INTO buying_chain_evidence
                          (id, project_id, retained_evidence_id, url, title, excerpt,
                           content_hash, extraction_location, observed_at, last_seen_at,
                           project_match_reason)
                        VALUES (:id, CAST(:project AS uuid), :retained, :url, :title,
                                :excerpt, :hash, 'synthetic-fixture', :now, :now,
                                'Explicit synthetic acceptance fixture for account contact.')
                    """),
                    {"id": buying_evidence_id, "project": project_id,
                     "retained": row["evidence_id"], "url": source_url,
                     "title": "Synthetic project contact fixture", "excerpt": quote,
                     "hash": evidence_key, "now": now},
                )
                connection.execute(
                    text("""
                        INSERT INTO buying_chain_claims
                          (id, project_id, entity_key, fingerprint, policy_version,
                           organization, person_name, title, category,
                           organization_relationship, person_organization_relationship,
                           person_project_relationship, evidence_strength, reason,
                           citations, public_contacts, observed_at)
                        VALUES (:id, CAST(:project AS uuid), :entity, :fingerprint,
                                'synthetic-acceptance-v1', 'DE CENTRAL Synthetic Operator',
                                'Synthetic Buyer', 'Project Contact', 'owner_operator',
                                'DIRECT', 'DIRECT', 'DIRECT', 'High',
                                'Synthetic source supports this project-scoped test contact.',
                                CAST(:citations AS jsonb), CAST(:methods AS jsonb), :now)
                    """),
                    {"id": claim_id, "project": project_id,
                     "entity": f"synthetic-contact:{project_id}",
                     "fingerprint": sha256(f"synthetic-contact:{project_id}".encode()).hexdigest(),
                     "citations": json.dumps([{
                         "evidence_id": str(buying_evidence_id), "url": source_url,
                         "quote": quote, "supports": "public_contact",
                     }]),
                     "methods": json.dumps([
                         {"kind": "email", "value": "buyer@example.invalid", "source_url": source_url, "quote": quote},
                         {"kind": "phone", "value": "+15555550101", "source_url": source_url, "quote": quote},
                     ]), "now": now},
                )
                connection.execute(
                    text("""
                        INSERT INTO buying_chain_runs
                          (id, project_id, input_hash, evidence_ids, claim_ids,
                           policy_version, status, documents_checked, candidates_added,
                           unresolved)
                        VALUES (:id, CAST(:project AS uuid), :hash,
                                CAST(:evidence AS jsonb), CAST(:claims AS jsonb),
                                'synthetic-acceptance-v1', 'complete', 1, 1, '[]'::jsonb)
                    """),
                    {"id": run_id, "project": project_id,
                     "hash": sha256(f"synthetic-run:{project_id}".encode()).hexdigest(),
                     "evidence": json.dumps([str(buying_evidence_id)]),
                     "claims": json.dumps([str(claim_id)])},
                )
                connection.execute(
                    text("""
                        INSERT INTO buying_chain_identity_links
                          (id, claim_id, entity_type, company_identity_id, reason, basis,
                           reviewed_by, source_evidence_id, source_version_hash, state)
                        VALUES (:id, :claim, 'company', :company,
                                'Explicit synthetic acceptance identity link.',
                                'attributed_review', 'test-fixture', :evidence, :hash, 'current')
                    """),
                    {"id": uuid4(), "claim": claim_id, "company": identity_id,
                     "evidence": buying_evidence_id, "hash": evidence_key},
                )
                connection.execute(
                    text("""
                        UPDATE browse_rows SET compact = compact || jsonb_build_object(
                          'contact_actions', CAST(:contact AS jsonb))
                        WHERE generation_id=CAST(:generation AS uuid)
                          AND project_id=CAST(:project AS uuid)
                    """),
                    {"contact": json.dumps(contact_actions),
                     "generation": manifest["generation_id"], "project": project_id},
                )
            connection.execute(
                text("""
                    INSERT INTO browse_customer_memberships
                    (generation_id, company_identity_id, project_id, organization_name,
                     role, supporting_evidence_count, last_evidence_update)
                    VALUES (CAST(:generation AS uuid), :identity, :project,
                            'DE CENTRAL Synthetic Operator', 'asset_operator', 1, :updated)
                """),
                {"generation": manifest["generation_id"], "identity": identity_id,
                 "project": row["project_id"], "updated": now},
            )
        if len(seen_projects) != len(target["project_ids"]):
            raise RuntimeError("Synthetic account fixture could not resolve every target project source.")
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
