"""Offline retained-source records traverse native GridLens ingestion."""

import hashlib
import json
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import func, select

pytest_plugins = ["test_customer_accounts"]


def _capacity_revision(record, capacity="640MW"):
    from gridlens.ingestion.adapters.retained_company_projects import retained_record_hash

    revised = deepcopy(record)
    revised["title"] = revised["title"].replace("480MW", capacity)
    revised["abstract"] = revised["abstract"].replace("480MW", capacity)
    context = revised["retained_company_project"]
    revised["source_body_hash"] = hashlib.sha256(revised["abstract"].encode()).hexdigest()
    context["body_hash"] = revised["source_body_hash"]
    for section in context["section_ranges"]:
        excerpt = revised["abstract"][section["start"] : section["end"]]
        section["sha256"] = hashlib.sha256(excerpt.encode()).hexdigest()
    for field in ("activity_quote", "project_quote"):
        context[field] = context[field].replace("480MW", capacity)
    revised["source_hash"] = retained_record_hash(revised)
    context["content_hash"] = revised["source_hash"]
    return revised


def _cancellation_status_record(record_path, output_root, *, status="Cancelled", capacity="480MW"):
    from gridlens.ingestion.adapters.retained_company_projects import retained_records

    source = json.loads(record_path.read_text())
    source["title"] = source["title"].replace("480MW", capacity) + f" — {status}"
    source["excerpts"] = [excerpt.replace("480MW", capacity) for excerpt in source["excerpts"]]
    target = output_root / "sources" / record_path.name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(source, ensure_ascii=False, indent=2) + "\n")
    encoded = target.read_bytes()
    body = "\n\n".join(source["excerpts"])
    (output_root / "source-hashes.json").write_text(
        json.dumps(
            [
                {
                    "file": "sources/" + target.name,
                    "sha256": hashlib.sha256(encoded).hexdigest(),
                    "url": source["url"],
                    "excerpt_sha256": hashlib.sha256(body.encode()).hexdigest(),
                }
            ],
            indent=2,
        )
        + "\n"
    )
    records, held = retained_records(output_root)
    assert len(records) == 1 and len(held) == 1
    return records[0]


def test_adapter_requires_one_local_project_site_activity_relation():
    from gridlens.ingestion.adapters.retained_company_projects import (
        _candidate,
        _source_project_aliases,
    )

    hq_and_actual_site = _candidate(
        [
            "Headquartered in Phoenix, Arizona. A data center campus in Mesa, Arizona is "
            "under construction."
        ]
    )
    assert hq_and_actual_site.state == "CANDIDATE"
    assert hq_and_actual_site.location == "Mesa, AZ"
    phase_scope = _candidate(
        [
            "Cedar City, Utah data center campus is planned and has a named location.",
            "South Campus construction has begun for its second building in Cedar City.",
        ]
    )
    assert phase_scope.state == "HOLD"
    ambiguous = [
        "North data center campus in Austin, Texas. South Campus construction has begun.",
        "North data center campus in Austin, Texas. A separate campus construction has begun.",
        "North data center campus in Austin, Texas. South Campus is planned to develop "
        "a new facility.",
        "A contractor reported a hypothetical data center campus in Austin, Texas under "
        "construction.",
        "A portfolio acquisition includes data center campuses in Austin, Texas and "
        "Houston, Texas.",
    ]
    assert all(_candidate([text]).state == "HOLD" for text in ambiguous)

    sibling_activity = _candidate(
        [
            "The new data center campus in Dallas, Texas is on hold while Beta facility "
            "is under construction."
        ]
    )
    sibling_building = _candidate(
        [
            "The new data center campus in Dallas, Texas exists.",
            "The second building at Beta campus is under construction.",
        ]
    )
    sibling_cross_section_building = _candidate(
        [
            "at its Ellendale, North Dakota data center campus.",
            "Ellendale campus is planned.",
            "Ellendale is a town. The second building at Beta campus is currently under "
            "construction.",
        ]
    )
    sibling_nearby_cross_section_building = _candidate(
        [
            "at its Ellendale, North Dakota data center campus.",
            "Ellendale campus is planned.",
            "The second building at Beta campus near Ellendale campus is currently under "
            "construction.",
        ]
    )
    cancelled = _candidate(
        [
            "The new data center campus in Dallas, Texas is cancelled.",
            "The facility is under construction.",
        ]
    )
    cancelled_anaphoric = _candidate(
        [
            "The new data center campus in Dallas, Texas is under construction. "
            "The campus was cancelled."
        ]
    )
    foreign_project_rename = _candidate(
        [
            "The new data center campus in Dallas, Texas is under construction.",
            "The competing campus, “Frontier”, will open soon.",
        ]
    )
    foreign_named_project = _candidate(
        [
            "The new data center campus in Dallas, Texas is under construction. "
            "Beta campus will be named “Frontier”."
        ]
    )
    foreign_competing_named_project = _candidate(
        [
            "The new data center campus in Dallas, Texas is under construction. "
            "The competing campus will be named “Frontier”."
        ]
    )
    negative_activity = _candidate(
        ["The new data center campus in Dallas, Texas is not currently under construction."]
    )
    hypothetical_activity = _candidate(
        ["For example, the new data center campus in Dallas, Texas is under construction."]
    )
    unrelated_power_source_activity = _candidate(
        [
            "The new data center campus in Dallas, Texas receives power from Beta facility, "
            "which is under construction."
        ]
    )
    anaphoric_foreign_facility_activity = _candidate(
        [
            "The new data center campus in Dallas, Texas exists. This facility receives "
            "power from Beta plant, which is under construction."
        ]
    )
    delayed_negation = _candidate(
        ["The new data center campus in Dallas, Texas is not yet currently under construction."]
    )
    hypothetical_after_predicate = _candidate(
        [
            "The new data center campus in Dallas, Texas is under construction in this "
            "hypothetical example."
        ]
    )
    contractor_other_facility = _candidate(
        [
            "The new data center campus in Dallas, Texas has a contractor whose other "
            "facility is under construction."
        ]
    )
    delayed_anaphoric_cancellation = _candidate(
        [
            "The new data center campus in Dallas, Texas is under construction. "
            "The campus consists of four buildings. The campus was cancelled."
        ]
    )
    assert all(
        item.state == "HOLD"
        for item in (
            sibling_activity,
            sibling_building,
            sibling_cross_section_building,
            sibling_nearby_cross_section_building,
            cancelled,
            cancelled_anaphoric,
            negative_activity,
            hypothetical_activity,
            unrelated_power_source_activity,
            anaphoric_foreign_facility_activity,
            delayed_negation,
            hypothetical_after_predicate,
            contractor_other_facility,
            delayed_anaphoric_cancellation,
        )
    )
    assert foreign_project_rename.project_name != "Frontier"
    assert foreign_named_project.project_name != "Frontier"
    assert foreign_competing_named_project.project_name != "Frontier"

    named_site = _candidate(
        [
            "The new data center campus in Dallas, Texas is under construction.",
            "A separate site will be called the new ‘Dallas East Campus’.",
        ]
    )
    assert named_site.state == "CANDIDATE"
    assert (
        _source_project_aliases(
            [
                "The new data center campus in Dallas, Texas is under construction.",
                "A separate site will be called the new ‘Dallas East Campus’.",
            ],
            named_site,
        )["project_aliases"]
        == []
    )
    foreign_alias_sections = [
        "The new data center campus in Dallas, Texas is under construction. "
        "Beta campus will be named “Frontier”."
    ]
    assert (
        _source_project_aliases(foreign_alias_sections, foreign_named_project)["project_aliases"]
        == []
    )
    assert (
        _source_project_aliases(foreign_alias_sections, foreign_competing_named_project)[
            "project_aliases"
        ]
        == []
    )
    land_alias_title = "DataBank Develops 480MW South Dallas Data Campus"
    for unrelated_land in (
        "The other land will become home to the new ‘Dallas Campus’.",
        "The Beta land will become home to the new ‘Dallas Campus’.",
    ):
        land_sections = [
            "The new data center campus in Dallas, Texas is under construction on "
            "100 acres of land.",
            unrelated_land,
        ]
        land_candidate = _candidate(land_sections)
        assert land_candidate.state == "CANDIDATE"
        assert (
            _source_project_aliases(
                land_sections,
                land_candidate,
                title=land_alias_title,
            )["project_aliases"]
            == []
        )


def test_retained_company_project_records_enter_native_pipeline(customer_db, tmp_path):
    from gridlens.ingestion.adapters.retained_company_projects import (
        FAMILY,
        RETRIEVAL_METHOD,
        SOURCE_ID,
        interpret_retained_company_project,
        retained_records,
    )
    from gridlens.ingestion.service import process_records
    from gridlens.intelligence.saved_browse import rebuild
    from gridlens.persistence.browse_invalidation import install
    from gridlens.persistence.models import (
        BrowseCustomerMembership,
        BuyingChainClaim,
        BuyingChainEvidence,
        BuyingChainIdentityLink,
        BuyingChainRun,
        ChangeEvent,
        Evidence,
        EvidencePackage,
        Interpretation,
        Job,
        PowerNeed,
        Project,
        Source,
    )

    root = Path(__file__).resolve().parents[3]
    fixture = root / "eval/customer-commercial-v1"
    retained, held = retained_records(fixture)
    assert len(retained) >= 2
    assert len(held) > 0
    assert all(interpret_retained_company_project(record) for record in retained)
    assert all("reference-customers" not in str(record) for record in retained)
    applied_hold = next(item for item in held if "sources/applied.json" in item["source_files"])
    assert applied_hold["state"] == "HOLD"
    assert "source-bound project/location/activity" in applied_hold["reason"]
    assert not any(
        "sources/applied.json" in record["retained_company_project"]["source_files"]
        for record in retained
    )

    source_definition = {
        "id": SOURCE_ID,
        "publisher": "retained offline public documents",
        "endpoint": "https://offline.invalid/retained",
        "family": FAMILY,
        "geography": "United States",
        "industries": ["data centers"],
        "retrieval_method": RETRIEVAL_METHOD,
        "cadence_hours": 24,
        "enabled": False,
        "registry_enabled": False,
    }
    worker = "retained-company-runtime-test"
    with customer_db.begin() as session:
        install(session.connection())
    with customer_db.begin() as session:
        session.add(Source(**source_definition))
        session.flush()
        job = Job(
            source_id=SOURCE_ID,
            status="running",
            lease_owner=worker,
            fence=1,
            lease_until=datetime.now(UTC) + timedelta(minutes=10),
        )
        session.add(job)
        session.flush()
        job_id = job.id

    with customer_db() as session:
        counts = process_records(
            session,
            job_id,
            worker,
            1,
            source_definition,
            retained,
            allow_model=False,
        )
    assert counts["retrieved_records"] == len(retained)
    assert counts["signals"] >= 1

    with customer_db.begin() as session:
        projects = session.scalars(select(Project)).all()
        needs = session.scalars(select(PowerNeed)).all()
        evidences = session.scalars(select(Evidence)).all()
        interpretations = session.scalars(select(Interpretation)).all()
        packages = session.scalars(select(EvidencePackage)).all()
        assert session.scalar(select(func.count()).select_from(Project)) >= 1
        assert len(needs) >= 1
        assert len(evidences) == len(retained)
        assert len(interpretations) == len(retained)
        assert all(need.required_mw is None for need in needs)
        for evidence in evidences:
            assert evidence.url.startswith("https://")
            assert evidence.provenance["retained_company_project"]["source_url"] == evidence.url
        for interpretation in interpretations:
            assessment = interpretation.assessment
            assert assessment["decision"] == "accepted"
            assert assessment["evidence_hash"]
            assert assessment["evidence"]["url"].startswith("https://")
        assert all(project.external_id for project in projects)
        assert not any(project.name == "Ellendale campus" for project in projects)
        databank_project = next(
            project for project in projects if project.name.startswith("Red Oak")
        )
        databank_record = next(
            record
            for record in retained
            if "sources/databank.json" in record["retained_company_project"]["source_files"]
        )
        assert databank_project.identity_facts["project_aliases"] == ["Red Oak Campus"]
        assert any(
            package.payload.get("capacity_claims")
            or package.payload.get("timeline_claims")
            or package.payload.get("commissioning_inputs")
            for package in packages
        )
        data_bank_packages = [
            package
            for package in packages
            if any(
                "databank.com" in evidence.url
                for evidence in evidences
                if evidence.id == package.evidence_id
            )
        ]
        assert data_bank_packages, [
            (project.name, project.location, project.region_status, project.region_state)
            for project in projects
            if "Red Oak" in project.location
        ]
        assert any(package.payload.get("capacity_claims") for package in data_bank_packages)

        from gridlens.intelligence.buying_chain import enrich_buying_chain

        databank_project = next(project for project in projects if "Red Oak" in project.location)
        databank_evidence = next(
            evidence for evidence in evidences if "databank.com" in evidence.url
        )
        buying_chain = enrich_buying_chain(
            session,
            databank_project.id,
            retained_only=True,
            retained_target_evidence_id=databank_evidence.id,
        )
        assert isinstance(buying_chain, dict)
        first_claims = session.scalars(
            select(BuyingChainClaim).where(BuyingChainClaim.project_id == databank_project.id)
        ).all()
        databank_claim = next(
            (
                claim
                for claim in first_claims
                if claim.organization == "DataBank" and claim.category == "owner_developer"
            ),
            None,
        )
        assert databank_claim is not None
        assert any(
            citation.get("supports") == "project_organization"
            and "Red Oak, TX" in citation.get("quote", "")
            for citation in databank_claim.citations
        )
        first_fingerprint = databank_claim.fingerprint
        enrich_buying_chain(
            session,
            databank_project.id,
            retained_only=True,
            retained_target_evidence_id=databank_evidence.id,
        )
        replay_claims = session.scalars(
            select(BuyingChainClaim).where(BuyingChainClaim.project_id == databank_project.id)
        ).all()
        assert len(replay_claims) == len(first_claims)
        assert any(claim.fingerprint == first_fingerprint for claim in replay_claims)
        current_link = session.scalar(
            select(BuyingChainIdentityLink).where(
                BuyingChainIdentityLink.claim_id == databank_claim.id,
                BuyingChainIdentityLink.entity_type == "company",
                BuyingChainIdentityLink.state == "current",
            )
        )
        assert current_link is not None and current_link.company_identity_id is not None
        project_scoped_company_id = current_link.company_identity_id

        cyrus_project = next(
            project for project in projects if project.name.startswith("new data center")
        )
        cyrus_evidence = next(evidence for evidence in evidences if "cyrusone.com" in evidence.url)
        cyrus_result = enrich_buying_chain(
            session,
            cyrus_project.id,
            retained_only=True,
            retained_target_evidence_id=cyrus_evidence.id,
        )
        assert isinstance(cyrus_result, dict)
        cyrus_claim = session.scalar(
            select(BuyingChainClaim).where(
                BuyingChainClaim.project_id == cyrus_project.id,
                BuyingChainClaim.organization == "CyrusOne",
                BuyingChainClaim.category == "project_customer",
            )
        )
        assert cyrus_claim is not None
        assert len(cyrus_claim.citations) == 1
        assert "agreement with Dallas based CyrusOne" in cyrus_claim.citations[0]["quote"]
        assert "Bosque County, Texas" in cyrus_claim.citations[0]["quote"]

    revised = _capacity_revision(databank_record)
    assert revised["source_hash"] != databank_record["source_hash"]
    assert interpret_retained_company_project(revised) is not None
    with customer_db() as session:
        revised_counts = process_records(
            session,
            job_id,
            worker,
            1,
            source_definition,
            [revised],
            allow_model=False,
        )
    assert revised_counts["retrieved_records"] == 1
    with customer_db.begin() as session:
        revised_evidence = session.scalar(
            select(Evidence).where(
                Evidence.url == revised["html_url"],
                Evidence.content_hash == revised["source_hash"],
            )
        )
        assert revised_evidence is not None
        enrich_buying_chain(
            session,
            databank_project.id,
            retained_only=True,
            retained_target_evidence_id=revised_evidence.id,
        )
        revised_claims = session.scalars(
            select(BuyingChainClaim).where(
                BuyingChainClaim.project_id == databank_project.id,
                BuyingChainClaim.organization == "DataBank",
                BuyingChainClaim.category == "owner_developer",
            )
        ).all()
        revised_claim = next(
            (
                claim
                for claim in revised_claims
                if any("640MW" in citation.get("quote", "") for citation in claim.citations)
            ),
            None,
        )
        assert revised_claim is not None
        revised_link = session.scalar(
            select(BuyingChainIdentityLink).where(
                BuyingChainIdentityLink.claim_id == revised_claim.id,
                BuyingChainIdentityLink.entity_type == "company",
                BuyingChainIdentityLink.state == "current",
            )
        )
        assert revised_link is not None
        if revised_link.company_identity_id != project_scoped_company_id:
            runs = session.scalars(
                select(BuyingChainRun)
                .where(BuyingChainRun.project_id == databank_project.id)
                .order_by(BuyingChainRun.created_at.desc())
                .limit(3)
            ).all()
            lineage = session.scalars(
                select(BuyingChainClaim)
                .where(BuyingChainClaim.project_id == databank_project.id)
                .order_by(BuyingChainClaim.created_at.desc())
                .limit(4)
            ).all()
            versions = session.scalars(
                select(BuyingChainEvidence)
                .where(BuyingChainEvidence.project_id == databank_project.id)
                .order_by(BuyingChainEvidence.observed_at.desc())
            ).all()
            diagnostic = {
                "expected_company_id": str(project_scoped_company_id),
                "actual_company_id": str(revised_link.company_identity_id),
                "runs": [
                    {
                        "id": str(run.id),
                        "claim_ids": run.claim_ids,
                        "evidence_ids": run.evidence_ids,
                        "created_at": run.created_at.isoformat(),
                    }
                    for run in runs
                ],
                "claims": [
                    {
                        "id": str(claim.id),
                        "fingerprint": claim.fingerprint,
                        "organization": claim.organization,
                        "category": claim.category,
                        "citations": claim.citations,
                    }
                    for claim in lineage
                ],
                "versions": [
                    {
                        "id": str(version.id),
                        "retained_evidence_id": str(version.retained_evidence_id),
                        "url": version.url,
                        "content_hash": version.content_hash,
                        "observed_at": version.observed_at.isoformat(),
                    }
                    for version in versions
                ],
            }
            raise AssertionError(f"Project scoped identity changed: {diagnostic!r}")
        assert "historical reported involvement" in revised_claim.reason.casefold()
        assert "not a finding of current legal ownership" in revised_claim.reason.casefold()

    before_generation = rebuild(customer_db)
    assert before_generation["status"] == "published"
    with customer_db() as session:
        before_memberships = session.scalar(
            select(func.count())
            .select_from(BrowseCustomerMembership)
            .where(
                BrowseCustomerMembership.generation_id == before_generation["generation_id"],
                BrowseCustomerMembership.project_id == databank_project.id,
            )
        )
    assert before_memberships >= 1

    cancellation_record = _cancellation_status_record(
        fixture / "sources/databank.json",
        tmp_path / "cancelled",
        status="Cancelled",
        capacity="640MW",
    )
    assert cancellation_record["retained_company_project"]["status"] == "adverse_status_review"
    assert interpret_retained_company_project(cancellation_record) is None
    with customer_db() as session:
        cancellation_counts = process_records(
            session,
            job_id,
            worker,
            1,
            source_definition,
            [cancellation_record],
            allow_model=False,
        )
    assert cancellation_counts["retrieved_records"] == 1
    with customer_db.begin() as session:
        cancellation_evidence = session.scalar(
            select(Evidence).where(
                Evidence.url == cancellation_record["html_url"],
                Evidence.content_hash == cancellation_record["source_hash"],
            )
        )
        assert cancellation_evidence is not None
        cancellation_interpretation = session.scalar(
            select(Interpretation).where(
                Interpretation.observation_id == cancellation_evidence.observation_id
            )
        )
        assert cancellation_interpretation is not None
        assert cancellation_interpretation.status == "rejected"
        assert (cancellation_interpretation.assessment or {}).get("decision") != "accepted"
        cancellation_need = session.scalar(
            select(PowerNeed).where(PowerNeed.project_id == databank_project.id)
        )
        assert cancellation_need is not None and not cancellation_need.active
        assert (
            session.scalar(
                select(func.count())
                .select_from(ChangeEvent)
                .where(
                    ChangeEvent.observation_id == cancellation_evidence.observation_id,
                    ChangeEvent.kind == "closed",
                )
            )
            >= 1
        )
    # A -> 640MW same-role revision preserves the project-scoped UUID. The
    # accepted -> adverse -> accepted sequence below must allocate a fresh ID.
    recovery_record = _capacity_revision(databank_record, "720MW")
    assert interpret_retained_company_project(recovery_record) is not None
    with customer_db() as session:
        recovery_counts = process_records(
            session,
            job_id,
            worker,
            1,
            source_definition,
            [recovery_record],
            allow_model=False,
        )
    assert recovery_counts["retrieved_records"] == 1
    with customer_db.begin() as session:
        recovery_evidence = session.scalar(
            select(Evidence).where(
                Evidence.url == recovery_record["html_url"],
                Evidence.content_hash == recovery_record["source_hash"],
            )
        )
        assert recovery_evidence is not None
        from gridlens.intelligence.buying_chain import enrich_buying_chain

        recovery_result = enrich_buying_chain(
            session,
            databank_project.id,
            retained_only=True,
            retained_target_evidence_id=recovery_evidence.id,
        )
        recovery_claims = session.scalars(
            select(BuyingChainClaim).where(
                BuyingChainClaim.project_id == databank_project.id,
                BuyingChainClaim.organization == "DataBank",
                BuyingChainClaim.category == "owner_developer",
            )
        ).all()
        recovery_claim = next(
            (
                claim
                for claim in recovery_claims
                if any("720MW" in citation.get("quote", "") for citation in claim.citations)
            ),
            None,
        )
        assert recovery_claim is not None, {
            "counts": recovery_counts,
            "result": recovery_result,
            "claims": [
                {
                    "id": str(claim.id),
                    "fingerprint": claim.fingerprint,
                    "citations": claim.citations,
                }
                for claim in recovery_claims
            ],
        }
        recovery_link = session.scalar(
            select(BuyingChainIdentityLink).where(
                BuyingChainIdentityLink.claim_id == recovery_claim.id,
                BuyingChainIdentityLink.entity_type == "company",
                BuyingChainIdentityLink.state == "current",
            )
        )
        assert recovery_link is not None and recovery_link.company_identity_id is not None
        assert recovery_link.company_identity_id != project_scoped_company_id

    before_replay_events = None
    with customer_db() as session:
        before_replay_events = session.scalar(
            select(func.count())
            .select_from(ChangeEvent)
            .where(ChangeEvent.observation_id == recovery_evidence.observation_id)
        )
    with customer_db() as session:
        replay_counts = process_records(
            session,
            job_id,
            worker,
            1,
            source_definition,
            [recovery_record],
            allow_model=False,
        )
    assert replay_counts["retrieved_records"] == 1
    with customer_db() as session:
        after_replay_events = session.scalar(
            select(func.count())
            .select_from(ChangeEvent)
            .where(ChangeEvent.observation_id == recovery_evidence.observation_id)
        )
    assert after_replay_events == before_replay_events

    after_generation = rebuild(customer_db)
    assert after_generation["status"] == "published"
    with customer_db() as session:
        after_memberships = session.scalar(
            select(func.count())
            .select_from(BrowseCustomerMembership)
            .where(
                BrowseCustomerMembership.generation_id == after_generation["generation_id"],
                BrowseCustomerMembership.project_id == databank_project.id,
            )
        )
    assert after_memberships >= 1

    withdrawal_record = _cancellation_status_record(
        fixture / "sources/databank.json",
        tmp_path / "withdrawn",
        status="Withdrawn",
        capacity="720MW",
    )
    with customer_db() as session:
        withdrawal_counts = process_records(
            session,
            job_id,
            worker,
            1,
            source_definition,
            [withdrawal_record],
            allow_model=False,
        )
    assert withdrawal_counts["retrieved_records"] == 1
    with customer_db.begin() as session:
        withdrawal_evidence = session.scalar(
            select(Evidence).where(
                Evidence.url == withdrawal_record["html_url"],
                Evidence.content_hash == withdrawal_record["source_hash"],
            )
        )
        assert withdrawal_evidence is not None
        withdrawal_need = session.scalar(
            select(PowerNeed).where(PowerNeed.project_id == databank_project.id)
        )
        assert withdrawal_need is not None and not withdrawal_need.active
        enrich_buying_chain(
            session,
            databank_project.id,
            retained_only=True,
            retained_target_evidence_id=withdrawal_evidence.id,
        )
    after_withdrawal_generation = rebuild(customer_db)
    with customer_db() as session:
        withdrawal_memberships = session.scalar(
            select(func.count())
            .select_from(BrowseCustomerMembership)
            .where(
                BrowseCustomerMembership.generation_id
                == after_withdrawal_generation["generation_id"],
                BrowseCustomerMembership.project_id == databank_project.id,
            )
        )
    assert withdrawal_memberships == 0
