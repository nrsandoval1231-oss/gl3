"""Singleton fact reads reuse their caller's current Project safely."""

import re
from datetime import date
from hashlib import sha256

from sqlalchemy import event

from gridlens.intelligence.customer_intelligence import project_customer_facts

pytest_plugins = ["test_equipment_intelligence"]


def test_preloaded_project_fact_read_matches_batch_and_skips_project_select(equipment_db):
    from test_equipment_intelligence import seed

    with equipment_db.begin() as session:
        _, project, _, _, _, _ = seed(
            session,
            body=(
                "Mock Permian Compression Station has 120 MW of campus development capacity. "
                "Construction will begin in Q2 2027."
            ),
        )
        expected = project_customer_facts(session, [project.id], generation=None)
        reads = []
        engine = session.get_bind()

        def capture(_conn, _cursor, statement, _parameters, _context, _many):
            if statement.lstrip().upper().startswith("SELECT"):
                reads.append(statement)

        event.listen(engine, "before_cursor_execute", capture)
        try:
            actual = project_customer_facts(
                session,
                [project.id],
                generation=None,
                preloaded_project=project,
            )
        finally:
            event.remove(engine, "before_cursor_execute", capture)

        assert actual == expected
        assert actual[str(project.id)][0]["capacity_claims"][0]["value_mw"] == "120"
        assert reads
        normalized = [statement.lower() for statement in reads]
        assert all(
            re.search(r"\b(?:from|join)\s+projects\b", statement) is None
            for statement in normalized
        )


def test_preloaded_project_rejected_current_source_does_not_load_owner_context(equipment_db):
    from test_equipment_intelligence import seed

    with equipment_db.begin() as session:
        _, project, _, _, interpretation, _ = seed(
            session,
            body="Mock Permian Compression Station has 120 MW of campus development capacity.",
        )
        interpretation.status = "rejected"
        session.flush()
        reads = []
        engine = session.get_bind()

        def capture(_conn, _cursor, statement, _parameters, _context, _many):
            if statement.lstrip().upper().startswith("SELECT"):
                reads.append(statement)

        event.listen(engine, "before_cursor_execute", capture)
        try:
            actual = project_customer_facts(
                session,
                [project.id],
                generation=None,
                preloaded_project=project,
            )
        finally:
            event.remove(engine, "before_cursor_execute", capture)

        assert actual[str(project.id)] == []
        normalized = [statement.lower() for statement in reads]
        assert all("company_project_memberships" not in statement for statement in normalized)
        assert all(
            re.search(r"\b(?:from|join)\s+projects\b", statement) is None
            for statement in normalized
        )


def _seed_owner_fact_project(session, *, suffix, owner, project_name, body=None):
    from gridlens.persistence.models import Evidence, Interpretation, Observation, Project, Source

    body = body or f"{owner}'s {project_name} is designed to host 400 MW of critical IT load."
    content_hash = sha256(body.encode()).hexdigest()
    source = Source(
        id=f"synthetic-owner-facts-{suffix}",
        publisher="Synthetic official fixture",
        endpoint="https://example.test/owner-facts",
        family="construction-permits",
        geography="Texas",
        industries=["data centers"],
        retrieval_method="ok-deq-public-review",
        health={},
    )
    session.add(source)
    session.flush()
    project = Project(
        identity_key=f"owner-facts-{suffix}",
        name=project_name,
        location="Austin, TX",
        source_id=source.id,
        external_id=f"site-{suffix}",
    )
    session.add(project)
    session.flush()
    observation = Observation(
        source_id=source.id,
        external_id=project.external_id,
        title=project_name,
        abstract=body,
        published_at=date.today(),
        url=f"https://example.test/owner-facts/{suffix}",
        content_hash=content_hash,
    )
    session.add(observation)
    session.flush()
    evidence = Evidence(
        observation_id=observation.id,
        content_hash=content_hash,
        title=project_name,
        abstract=body,
        url=observation.url,
        published_at=observation.published_at,
        extraction_location="Synthetic project release",
    )
    session.add(evidence)
    session.flush()
    session.add(
        Interpretation(
            observation_id=observation.id,
            status="accepted",
            content_hash=content_hash,
            assessment={
                "semantic_hash": content_hash,
                "evidence_hash": evidence.content_hash,
                "decision": "accepted",
                "project_identity_key": project.identity_key,
                "evidence": {"id": str(evidence.id), "url": evidence.url},
            },
        )
    )
    session.flush()
    return project


def test_batched_owner_context_is_project_scoped_and_matches_singleton_reads(
    equipment_db, monkeypatch
):
    with equipment_db.begin() as session:
        alpha = _seed_owner_fact_project(
            session,
            suffix="alpha",
            owner="Applied Digital",
            project_name="Ellendale campus",
            body=(
                "Applied Digital's Ellendale campus is under construction. "
                "The phase 1 design of the site will deliver up to 400 MW of critical IT load."
            ),
        )
        beta = _seed_owner_fact_project(
            session,
            suffix="beta",
            owner="Beta Holdings",
            project_name="Reno campus",
            body=(
                "Beta Holdings's Reno campus is designed to host 400 MW of critical IT load. "
                "Applied Digital's Reno campus is designed to host 600 MW of critical IT load."
            ),
        )
        owner_map = {
            str(alpha.id): ["Applied Digital"],
            str(beta.id): ["Beta Holdings"],
        }
        monkeypatch.setattr(
            "gridlens.intelligence.customer_intelligence._verified_project_owner_names",
            lambda _session, project_ids, **_kwargs: {
                str(project_id): owner_map.get(str(project_id), []) for project_id in project_ids
            },
        )

        batched = project_customer_facts(session, [alpha.id, beta.id], generation=None)
        alpha_singleton = project_customer_facts(
            session, [alpha.id], generation=None, preloaded_project=alpha
        )
        beta_singleton = project_customer_facts(
            session, [beta.id], generation=None, preloaded_project=beta
        )

        assert batched[str(alpha.id)] == alpha_singleton[str(alpha.id)]
        assert batched[str(beta.id)] == beta_singleton[str(beta.id)]
        assert batched[str(alpha.id)][0]["capacity_claims"][0]["value_mw"] == "400"
        assert batched[str(beta.id)][0]["capacity_claims"][0]["value_mw"] == "400"
        assert len(batched[str(beta.id)][0]["capacity_claims"]) == 1
        assert "Beta Holdings" in batched[str(beta.id)][0]["capacity_claims"][0]["quote"]
