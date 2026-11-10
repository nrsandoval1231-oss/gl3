"""Synthetic acceptance cases for durable account and project identity."""

from datetime import UTC, datetime
from hashlib import sha256

from sqlalchemy import func, select

from gridlens.intelligence.company_graph import company_graph
from gridlens.intelligence.customer_results import _group_id, group_projects, groups
from gridlens.intelligence.saved_browse import current_generation, rebuild
from gridlens.persistence.contact_models import CompanyRelationshipAssertion
from gridlens.persistence.models import (
    BrowseCustomerMembership,
    BrowseRow,
    BuyingChainClaim,
    BuyingChainEvidence,
    BuyingChainIdentityLink,
    BuyingChainRun,
    CompanyIdentity,
    CompanyProjectMembership,
    Evidence,
    IdentityIdentifier,
    NeedObservation,
    PersonIdentity,
    PowerNeed,
    Project,
)

pytest_plugins = ["test_saved_browse"]


def _content_hash(value: str) -> str:
    return sha256(value.encode("utf-8")).hexdigest()


def _supported_company_claim(session, *, project_id, company_id, source, name, key):
    claim = BuyingChainClaim(
        project_id=project_id,
        entity_key=key,
        fingerprint=_content_hash(f"claim:{key}"),
        policy_version="synthetic-account-acceptance-v1",
        organization=name,
        person_name=None,
        title="Operator",
        category="operator",
        organization_relationship="DIRECT",
        person_organization_relationship="UNKNOWN",
        person_project_relationship="UNKNOWN",
        evidence_strength="high",
        reason="Synthetic source-bound account identity fixture.",
        citations=[
            {
                "evidence_id": str(source.id),
                "url": source.url,
                "quote": source.excerpt,
                "supports": "project_organization",
            }
        ],
        public_contacts=[],
        observed_at=source.observed_at,
    )
    session.add(claim)
    session.flush()
    session.add(
        BuyingChainIdentityLink(
            claim_id=claim.id,
            entity_type="company",
            company_identity_id=company_id,
            reason="Synthetic explicit current identity binding.",
            basis="attributed_review",
            reviewed_by="synthetic-test-reviewer",
            source_evidence_id=source.id,
            source_version_hash=source.content_hash,
            state="current",
        )
    )
    return claim


def _contact_claim(session, *, project_id, company_id, person_id, source, organization, name, key):
    quote = f"Synthetic project source identifies {name} as {organization}'s project contact."
    role_quote = f"{name} is employed by {organization}."
    assignment_quote = f"{name} is the project contact for {organization}."
    contact_quote = f"Public project contact: {name} <{key}@example.test>"
    claim = BuyingChainClaim(
        project_id=project_id,
        entity_key=key,
        fingerprint=_content_hash(f"contact:{key}"),
        policy_version="synthetic-account-acceptance-v1",
        organization=organization,
        person_name=name,
        title="Project Contact",
        category="owner",
        organization_relationship="DIRECT",
        person_organization_relationship="EMPLOYEE",
        person_project_relationship="PROJECT_CONTACT",
        evidence_strength="high",
        reason="Synthetic project contact fixture; no authority is asserted.",
        citations=[
            {
                "evidence_id": str(source.id),
                "url": source.url,
                "quote": quote,
                "supports": "project_organization",
            },
            {
                "evidence_id": str(source.id),
                "url": source.url,
                "quote": role_quote,
                "supports": "organization_person_role",
            },
            {
                "evidence_id": str(source.id),
                "url": source.url,
                "quote": assignment_quote,
                "supports": "person_project_assignment",
            },
            {
                "evidence_id": str(source.id),
                "url": source.url,
                "quote": contact_quote,
                "supports": "public_contact",
            },
        ],
        public_contacts=[
            {
                "kind": "email",
                "value": f"{key}@example.test",
                "source_url": source.url,
                "quote": contact_quote,
            }
        ],
        observed_at=source.observed_at,
    )
    session.add(claim)
    session.flush()
    session.add_all(
        [
            BuyingChainIdentityLink(
                claim_id=claim.id,
                entity_type="company",
                company_identity_id=company_id,
                reason="Synthetic company identity is source-bound.",
                basis="attributed_review",
                reviewed_by="synthetic-test-reviewer",
                source_evidence_id=source.id,
                source_version_hash=source.content_hash,
                state="current",
            ),
            BuyingChainIdentityLink(
                claim_id=claim.id,
                entity_type="person",
                person_identity_id=person_id,
                reason="Synthetic person identity is source-bound to this company claim.",
                basis="attributed_review",
                reviewed_by="synthetic-test-reviewer",
                source_evidence_id=source.id,
                source_version_hash=source.content_hash,
                state="current",
            ),
        ]
    )
    return claim


def test_twelve_synthetic_documents_five_supported_aliases_roll_up_three_sites(saved_db):
    """Three sites and twelve retained documents stay one account and three projects."""
    from test_saved_browse import seed

    seed(saved_db, count=3, histories=4)
    assert rebuild(saved_db)["status"] == "published"

    aliases = [
        "Northstar Field Operations",
        "Northstar Operating Company",
        "Northstar Production LLC",
        "Northstar Resources Group",
        "Northstar Texas Operations",
    ]
    operator_name = "Northstar Synthetic Operator"
    with saved_db.begin() as session:
        generation = current_generation(session)
        projects = session.scalars(
            select(Project).order_by(func.length(Project.external_id), Project.external_id)
        ).all()
        rows = {
            row.project_id: row
            for row in session.scalars(
                select(BrowseRow).where(BrowseRow.generation_id == generation.id)
            ).all()
        }
        operator = CompanyIdentity(rrc_operator_number="12345")
        session.add(operator)
        session.flush()

        retained_documents = session.scalars(
            select(Evidence).order_by(Evidence.url, Evidence.id)
        ).all()
        assert len(retained_documents) == 12
        by_project: dict[object, list[Evidence]] = {project.id: [] for project in projects}
        for evidence in retained_documents:
            need_id = session.scalar(
                select(NeedObservation.need_id).where(
                    NeedObservation.observation_id == evidence.observation_id
                )
            )
            project_id = session.scalar(select(PowerNeed.project_id).where(PowerNeed.id == need_id))
            by_project[project_id].append(evidence)

        source_rows = []
        claims_by_project: dict[object, list[object]] = {project.id: [] for project in projects}
        for project_index, project in enumerate(projects):
            row = rows[project.id]
            metadata = {
                **row.compact.get("project_metadata", {}),
                "sector": "oil_gas",
                "title": f"Synthetic well site {project_index + 1}",
                "operator": operator_name,
                "oil_gas": {"operator_number": "12345"},
                "asset_identity": {
                    "kind": "us_well_api",
                    "value": f"421650{project_index + 1:04d}",
                    "identity_validated": True,
                },
            }
            row.compact = {**row.compact, "project_metadata": metadata}
            session.add(
                BrowseCustomerMembership(
                    generation_id=generation.id,
                    company_identity_id=operator.id,
                    project_id=project.id,
                    organization_name=operator_name,
                    role="asset_operator",
                    supporting_evidence_count=4,
                )
            )
            project_evidence = by_project[project.id]
            assert len(project_evidence) == 4
            session.add(
                CompanyProjectMembership(
                    company_identity_id=operator.id,
                    project_id=project.id,
                    role="asset_operator",
                    organization_name=operator_name,
                    source_id=project.source_id,
                    source_evidence_id=project_evidence[0].id,
                    source_version_hash=project_evidence[0].content_hash,
                    decision_basis="official_operator_number",
                    operator_number="12345",
                )
            )
            for _doc_index, _retained in enumerate(project_evidence):
                index = len(source_rows)
                name = aliases[index] if index < len(aliases) else operator_name
                excerpt = f"Synthetic source {index + 1} identifies {name} as project operator."
                digest = _content_hash(f"synthetic-company-document:{index}")
                source = BuyingChainEvidence(
                    project_id=project.id,
                    url=f"https://example.test/synthetic-company-document/{index + 1}",
                    title=f"Synthetic operator source document {index + 1}",
                    excerpt=excerpt,
                    content_hash=digest,
                    extraction_location="Synthetic fixture",
                    observed_at=datetime.now(UTC),
                    last_seen_at=datetime.now(UTC),
                    project_match_reason="Synthetic exact project binding.",
                )
                session.add(source)
                session.flush()
                claim = _supported_company_claim(
                    session,
                    project_id=project.id,
                    company_id=operator.id,
                    source=source,
                    name=name,
                    key=f"synthetic-operator-doc-{index + 1}",
                )
                if index < len(aliases):
                    session.add(
                        IdentityIdentifier(
                            entity_type="company",
                            company_identity_id=operator.id,
                            identifier_type="alias",
                            normalized_value=aliases[index].casefold(),
                            source_evidence_id=source.id,
                            source_version_hash=source.content_hash,
                            reason="Synthetic alias supported by this current source version.",
                        )
                    )
                source_rows.append(source)
                claims_by_project[project.id].append(claim)

        for project in projects:
            project_sources = [source for source in source_rows if source.project_id == project.id]
            project_claims = claims_by_project[project.id]
            session.add(
                BuyingChainRun(
                    project_id=project.id,
                    input_hash=_content_hash(f"synthetic-run:{project.id}"),
                    evidence_ids=[str(source.id) for source in project_sources],
                    claim_ids=[str(claim.id) for claim in project_claims],
                    policy_version="synthetic-account-acceptance-v1",
                    status="complete",
                    documents_checked=len(project_sources),
                    candidates_added=len(project_claims),
                    unresolved=[],
                )
            )

    with saved_db() as session:
        result = groups(session, sector="oil_gas", selected_generation=generation)
        assert result["total"] == 1
        account = result["items"][0]
        assert account["id"] == _group_id("rrc:12345")
        assert account["project_count"] == 3
        children = group_projects(
            session,
            account["id"],
            sector="oil_gas",
            parent_token=result["cohort_token"],
            limit=25,
            selected_generation=generation,
        )
        assert children["total"] == 3
        assert len({item["project_id"] for item in children["items"]}) == 3
        graph = company_graph(session, operator.id)
        assert {item["value"] for item in graph["company"]["aliases"]} == {
            alias.casefold() for alias in aliases
        }
        assert len(graph["projects"]) == 3
        graph_evidence_ids = {item["id"] for item in graph["evidence"]}
        assert {str(source.id) for source in source_rows} <= graph_evidence_ids
        assert session.scalar(select(func.count()).select_from(BuyingChainEvidence)) == 12

    amended_project = projects[0]
    amendment_hash = _content_hash("synthetic-existing-project-amendment")
    with saved_db.begin() as session:
        amendment = BuyingChainEvidence(
            project_id=amended_project.id,
            url="https://example.test/synthetic-company-document/1-amendment",
            title="Synthetic update to an existing operator document",
            excerpt=f"Amended synthetic record confirms {operator_name} for the same site.",
            content_hash=amendment_hash,
            extraction_location="Synthetic fixture amendment",
            observed_at=datetime.now(UTC),
            last_seen_at=datetime.now(UTC),
            project_match_reason="Synthetic amendment for the existing physical site.",
        )
        session.add(amendment)
        session.flush()
        claim = _supported_company_claim(
            session,
            project_id=amended_project.id,
            company_id=operator.id,
            source=amendment,
            name=operator_name,
            key="synthetic-existing-project-amendment",
        )
        run = session.scalar(
            select(BuyingChainRun)
            .where(BuyingChainRun.project_id == amended_project.id)
            .order_by(BuyingChainRun.created_at.desc(), BuyingChainRun.id.desc())
        )
        assert run is not None
        run.evidence_ids = [*run.evidence_ids, str(amendment.id)]
        run.claim_ids = [*run.claim_ids, str(claim.id)]
        run.documents_checked += 1
        run.candidates_added += 1

    with saved_db() as session:
        after_amendment = groups(session, sector="oil_gas", selected_generation=generation)
        assert after_amendment["total"] == 1
        assert after_amendment["items"][0]["id"] == _group_id("rrc:12345")
        assert after_amendment["items"][0]["project_count"] == 3
        assert session.scalar(select(func.count()).select_from(BuyingChainEvidence)) == 13


def test_two_synthetic_campuses_under_one_owner_remain_distinct_projects(saved_db):
    from test_saved_browse import seed

    seed(saved_db, count=2, histories=1)
    assert rebuild(saved_db)["status"] == "published"
    with saved_db.begin() as session:
        generation = current_generation(session)
        projects = session.scalars(
            select(Project).order_by(func.length(Project.external_id), Project.external_id)
        ).all()
        rows = {
            row.project_id: row
            for row in session.scalars(
                select(BrowseRow).where(BrowseRow.generation_id == generation.id)
            ).all()
        }
        owner = CompanyIdentity()
        session.add(owner)
        session.flush()
        for index, project in enumerate(projects):
            campus = f"Synthetic Owner Campus {index + 1}"
            # Account child rows intentionally use the canonical persisted
            # Project.name; keep the fixture's physical project record aligned
            # with the asserted display names.
            project.name = campus
            row = rows[project.id]
            row.compact = {
                **row.compact,
                "project_metadata": {
                    **row.compact.get("project_metadata", {}),
                    "sector": "data_centers",
                    "title": campus,
                    "data_center": {"owner_developer": "Synthetic Campus Owner"},
                    "asset_identity": {
                        "kind": "campus",
                        "value": f"synthetic-campus-{index + 1}",
                        "identity_validated": True,
                    },
                },
            }
            session.add(
                BrowseCustomerMembership(
                    generation_id=generation.id,
                    company_identity_id=owner.id,
                    project_id=project.id,
                    organization_name="Synthetic Campus Owner",
                    role="owner_developer",
                    supporting_evidence_count=1,
                )
            )

    with saved_db() as session:
        result = groups(session, sector="data_centers", selected_generation=generation)
        assert result["total"] == 1
        account = result["items"][0]
        assert account["project_count"] == 2
        children = group_projects(
            session,
            account["id"],
            sector="data_centers",
            parent_token=result["cohort_token"],
            limit=25,
            selected_generation=generation,
        )
        assert children["total"] == 2
        assert {item["name"] for item in children["items"]} == {
            "Synthetic Owner Campus 1",
            "Synthetic Owner Campus 2",
        }
        assert len({item["project_id"] for item in children["items"]}) == 2


def test_supported_subsidiary_keeps_legal_identity_and_contact_authority_separate(
    saved_db, monkeypatch
):
    """Real guard abstains; an attribution-only seam isolates identity separation."""
    from test_saved_browse import seed

    seed(saved_db, count=2, histories=1)
    assert rebuild(saved_db)["status"] == "published"
    parent_name = "Synthetic Holdings Inc"
    subsidiary_name = "Synthetic Campus OpCo LLC"
    with saved_db.begin() as session:
        generation = current_generation(session)
        projects = session.scalars(
            select(Project).order_by(func.length(Project.external_id), Project.external_id)
        ).all()
        rows = {
            row.project_id: row
            for row in session.scalars(
                select(BrowseRow).where(BrowseRow.generation_id == generation.id)
            ).all()
        }
        owner_identities = [CompanyIdentity(), CompanyIdentity()]
        people = [PersonIdentity(), PersonIdentity()]
        session.add_all([*owner_identities, *people])
        session.flush()

        claims_by_project: dict[object, list[object]] = {project.id: [] for project in projects}
        for index, project in enumerate(projects):
            company_name = parent_name if index == 0 else subsidiary_name
            contact_name = f"Synthetic {'Parent' if index == 0 else 'Subsidiary'} Contact"
            evidence = session.scalar(
                select(Evidence)
                .join(NeedObservation, NeedObservation.observation_id == Evidence.observation_id)
                .join(PowerNeed, PowerNeed.id == NeedObservation.need_id)
                .where(PowerNeed.project_id == project.id)
            )
            assert evidence is not None
            row = rows[project.id]
            row.compact = {
                **row.compact,
                "project_metadata": {
                    **row.compact.get("project_metadata", {}),
                    "sector": "data_centers",
                    "title": f"Synthetic {('Parent' if index == 0 else 'Subsidiary')} Campus",
                    "data_center": {"owner_developer": company_name},
                    "asset_identity": {
                        "kind": "campus",
                        "value": f"synthetic-family-campus-{index + 1}",
                        "identity_validated": True,
                    },
                },
            }
            session.add_all(
                [
                    BrowseCustomerMembership(
                        generation_id=generation.id,
                        company_identity_id=owner_identities[index].id,
                        project_id=project.id,
                        organization_name=company_name,
                        role="owner_developer",
                        supporting_evidence_count=1,
                    ),
                    CompanyProjectMembership(
                        company_identity_id=owner_identities[index].id,
                        project_id=project.id,
                        role="owner_developer",
                        organization_name=company_name,
                        source_id=project.source_id,
                        source_evidence_id=evidence.id,
                        source_version_hash=evidence.content_hash,
                        decision_basis="synthetic_source_bound_owner",
                        operator_number="000001",
                    ),
                ]
            )
            alias_source = BuyingChainEvidence(
                project_id=project.id,
                url=f"https://example.test/synthetic-family/{index + 1}",
                title="Synthetic legal entity and project contact record",
                excerpt=(
                    f"{parent_name} is the parent company of {subsidiary_name}. "
                    f"{company_name} maintains a separate project contact. "
                    f"{contact_name} is employed by {company_name}. "
                    f"{contact_name} is the project contact for {company_name}. "
                    f"Synthetic project source identifies {contact_name} as "
                    f"{company_name}'s project contact. "
                    f"Public project contact: {contact_name} "
                    f"<synthetic-family-contact-{index}@example.test>"
                ),
                content_hash=_content_hash(f"family-alias:{index}"),
                extraction_location="Synthetic fixture",
                observed_at=datetime.now(UTC),
                last_seen_at=datetime.now(UTC),
                project_match_reason="Synthetic current project binding.",
            )
            session.add(alias_source)
            session.flush()
            name_claim = _supported_company_claim(
                session,
                project_id=project.id,
                company_id=owner_identities[index].id,
                source=alias_source,
                name=company_name,
                key=f"family-company-{index}",
            )
            contact = _contact_claim(
                session,
                project_id=project.id,
                company_id=owner_identities[index].id,
                person_id=people[index].id,
                source=alias_source,
                organization=company_name,
                name=contact_name,
                key=f"synthetic-family-contact-{index}",
            )
            session.add(
                IdentityIdentifier(
                    entity_type="company",
                    company_identity_id=owner_identities[index].id,
                    identifier_type="legal_name",
                    normalized_value=company_name.casefold(),
                    source_evidence_id=alias_source.id,
                    source_version_hash=alias_source.content_hash,
                    reason="Synthetic source-backed distinct legal entity.",
                )
            )
            claims_by_project[project.id].extend([name_claim, contact])
            if index == 0:
                relation_source = alias_source

        # Both names are current on the source that supports the directional
        # family assertion. It links the legal identities without merging them.
        session.add(
            CompanyRelationshipAssertion(
                source_company_id=owner_identities[0].id,
                target_company_id=owner_identities[1].id,
                relationship_type="subsidiary",
                source_evidence_id=relation_source.id,
                source_version_hash=relation_source.content_hash,
                reason="Synthetic explicitly supported parent/subsidiary statement.",
                actor="synthetic-test-reviewer",
                idempotency_key="synthetic-parent-subsidiary-assertion",
            )
        )

        # The relationship statement is on the parent's project, so add a
        # separately linked current subsidiary claim to that same source/run.
        related_claim = _supported_company_claim(
            session,
            project_id=projects[0].id,
            company_id=owner_identities[1].id,
            source=relation_source,
            name=subsidiary_name,
            key="family-subsidiary-on-parent-source",
        )
        claims_by_project[projects[0].id].append(related_claim)
        for project in projects:
            source_ids = session.scalars(
                select(BuyingChainEvidence.id).where(BuyingChainEvidence.project_id == project.id)
            ).all()
            session.add(
                BuyingChainRun(
                    project_id=project.id,
                    input_hash=_content_hash(f"family-run:{project.id}"),
                    evidence_ids=[str(source_id) for source_id in source_ids],
                    claim_ids=[str(claim.id) for claim in claims_by_project[project.id]],
                    policy_version="synthetic-account-acceptance-v1",
                    status="complete",
                    documents_checked=len(source_ids),
                    candidates_added=len(claims_by_project[project.id]),
                    unresolved=[],
                )
            )

    with saved_db() as session:
        account_page = groups(session, sector="data_centers", selected_generation=generation)
        assert account_page["total"] == 2
        assert {item["name"] for item in account_page["items"]} == {
            parent_name,
            subsidiary_name,
        }
        parent_graph = company_graph(session, owner_identities[0].id)
        subsidiary_graph = company_graph(session, owner_identities[1].id)
        assert parent_graph["company"]["id"] != subsidiary_graph["company"]["id"]
        assert {item["value"] for item in parent_graph["company"]["aliases"]} == {
            parent_name.casefold()
        }
        assert {item["value"] for item in subsidiary_graph["company"]["aliases"]} == {
            subsidiary_name.casefold()
        }
        assert parent_graph["relationships"] == [
            {
                **parent_graph["relationships"][0],
                "source_company_id": str(owner_identities[0].id),
                "target_company_id": str(owner_identities[1].id),
                "relationship_type": "subsidiary",
                "status": "current",
                "support_status": "operator_assertion_unverified",
            }
        ]
        assert parent_graph["relationships"][0]["source_quote"].find(parent_name) < parent_graph[
            "relationships"
        ][0]["source_quote"].find(subsidiary_name)

        from gridlens.intelligence import company_contact_attribution
        from gridlens.intelligence.buying_chain import buying_chain_views

        project_ids = {project.id for project in projects}
        production_views = buying_chain_views(session, project_ids)
        assert not any(
            candidate.get("public_contacts")
            for view in production_views.values()
            for candidate in view["candidates"]
        )

        expected_company_by_person = {
            str(people[0].id): str(owner_identities[0].id),
            str(people[1].id): str(owner_identities[1].id),
        }

        def test_only_identity_attribution_seam(_session, candidate_views):
            # This narrowly scoped seam isolates the identity-bound contact
            # projection behavior from production native-source attribution.
            # The fixture below verifies the source-current claim, exact
            # company/person links, and method values before exposing them.
            for view in candidate_views:
                for candidate in view.get("candidates", []):
                    person_id = candidate.get("person_identity_id")
                    if person_id not in expected_company_by_person:
                        continue
                    assert (
                        candidate.get("company_identity_id")
                        == expected_company_by_person[person_id]
                    )
                    assert any(
                        evidence.get("supports") == "public_contact"
                        and evidence.get("current_support") is True
                        for evidence in candidate.get("evidence", [])
                    )

        monkeypatch.setattr(
            company_contact_attribution,
            "filter_unbound_company_contacts",
            test_only_identity_attribution_seam,
        )
        views = buying_chain_views(session, project_ids)
        contact_claims = session.scalars(
            select(BuyingChainClaim).where(
                BuyingChainClaim.id.in_(
                    [claims_by_project[project.id][1].id for project in projects]
                )
            )
        ).all()
        assert len(contact_claims) == 2
        assert {
            claim.person_name: claim.public_contacts[0]["value"] for claim in contact_claims
        } == {
            "Synthetic Parent Contact": "synthetic-family-contact-0@example.test",
            "Synthetic Subsidiary Contact": "synthetic-family-contact-1@example.test",
        }
        company_links = session.scalars(
            select(BuyingChainIdentityLink).where(
                BuyingChainIdentityLink.claim_id.in_([claim.id for claim in contact_claims]),
                BuyingChainIdentityLink.entity_type == "company",
            )
        ).all()
        person_links = session.scalars(
            select(BuyingChainIdentityLink).where(
                BuyingChainIdentityLink.claim_id.in_([claim.id for claim in contact_claims]),
                BuyingChainIdentityLink.entity_type == "person",
            )
        ).all()
        claims_by_name = {claim.person_name: claim for claim in contact_claims}
        assert {
            claim.person_name: next(
                link.company_identity_id for link in company_links if link.claim_id == claim.id
            )
            for claim in contact_claims
        } == {
            "Synthetic Parent Contact": owner_identities[0].id,
            "Synthetic Subsidiary Contact": owner_identities[1].id,
        }
        assert {
            claim.person_name: next(
                link.person_identity_id for link in person_links if link.claim_id == claim.id
            )
            for claim in contact_claims
        } == {
            "Synthetic Parent Contact": people[0].id,
            "Synthetic Subsidiary Contact": people[1].id,
        }
        assert set(claims_by_name) == {
            "Synthetic Parent Contact",
            "Synthetic Subsidiary Contact",
        }
        contact_candidates = [
            candidate
            for view in views.values()
            for candidate in view["candidates"]
            if candidate.get("person_identity_id")
        ]
        assert {candidate["person_identity_id"] for candidate in contact_candidates} == set(
            expected_company_by_person
        )
        parent_contact = next(
            item for item in contact_candidates if item["person_identity_id"] == str(people[0].id)
        )
        subsidiary_contact = next(
            item for item in contact_candidates if item["person_identity_id"] == str(people[1].id)
        )
        assert parent_contact["company_identity_id"] == str(owner_identities[0].id)
        assert subsidiary_contact["company_identity_id"] == str(owner_identities[1].id)
        assert parent_contact["public_contacts"][0]["value"] == (
            "synthetic-family-contact-0@example.test"
        )
        assert subsidiary_contact["public_contacts"][0]["value"] == (
            "synthetic-family-contact-1@example.test"
        )
