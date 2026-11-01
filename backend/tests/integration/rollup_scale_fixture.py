"""Fast synthetic frozen browse generation for customer rollup scale checks.

This fixture intentionally bypasses qualification rebuilds. Its rows are
synthetic presentation snapshots and must never be described as retained data.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, date, datetime, timedelta
from uuid import uuid4

from sqlalchemy import insert

from gridlens.domain.regional_scope import classify_project_region
from gridlens.intelligence.saved_browse import POLICY_VERSION
from gridlens.persistence.models import (
    BrowseCustomerMembership,
    BrowseGeneration,
    BrowseRow,
    BrowseState,
    CompanyIdentity,
    Evidence,
    Interpretation,
    NeedObservation,
    Observation,
    PowerNeed,
    Project,
    Source,
)


def _group_id(key: str) -> str:
    return "cg_" + hashlib.md5(key.encode(), usedforsecurity=False).hexdigest()


def seed_scale_corpus(factory, total_rows: int = 2098) -> dict:
    """Insert a synthetic generation with representative customer group sizes.

    The supplied factory must point at a fresh disposable test schema. The
    fixture inserts canonical Projects and generation-bound browse rows in
    bulk, avoiding the expensive per-project qualification pipeline.
    """
    if total_rows < 2098:
        raise ValueError("total_rows must leave room for all representative groups")

    generation_id = uuid4()
    now = datetime.now(UTC)
    de_number = "4216500001"
    diamond_number = "4216500002"
    amazon_name = "AMAZON DATA SERVICES, INC"
    source_id = "synthetic-rollup-scale"
    company_ids = [uuid4() for _ in range(3)]
    dc_customer_ids = [uuid4() for _ in range(12)]

    definitions: list[dict] = []
    for index in range(48):
        definitions.append(
            {
                "kind": "de_central",
                "index": index,
                "sector": "oil_gas",
                "operator_number": de_number,
                "operator": "DE CENTRAL Synthetic Operator",
                "title": (
                    "STORMCHASER Synthetic Asset" if index == 2 else f"DE CENTRAL Asset {index:02d}"
                ),
                "location": "Texas" if index == 0 else "New Mexico",
                "stage": "permit_issued" if index == 1 else "well_permitted",
                "rank": 9999 if index == 47 else 1,
            }
        )
    for index in range(159):
        definitions.append(
            {
                "kind": "diamondback",
                "index": index,
                "sector": "oil_gas",
                "operator_number": diamond_number,
                "operator": "Diamondback Synthetic Operator",
                "title": f"Diamondback Asset {index:03d}",
                "location": "Texas",
                "stage": "well_permitted",
                "rank": 900,
            }
        )
    for index in range(3):
        definitions.append(
            {
                "kind": "amazon",
                "index": index,
                "sector": "data_centers",
                "operator_number": None,
                "operator": None,
                "title": f"Amazon Synthetic TDLR Facility {index}",
                "location": "Texas",
                "stage": "permit_issued",
                "rank": 800,
            }
        )
    # Match the retained aggregate counts: 1,980 oil/gas rows, 18 data-center
    # rows, and 100 other rows. DC project groups comprise Amazon's three
    # unconfirmed identities plus 15 projects across 12 distinct companies.
    for index in range(15):
        company_index = index if index < 9 else 9 + (index - 9) // 2
        definitions.append(
            {
                "kind": "dc_customer",
                "index": index,
                "company_index": company_index,
                "sector": "data_centers",
                "operator_number": None,
                "operator": f"Synthetic Data Center Customer {company_index:02d}",
                "title": f"Synthetic Data Center Facility {index:02d}",
                "location": "Texas" if index % 2 == 0 else "New Mexico",
                "stage": "construction_started" if index % 2 else "permit_issued",
                "rank": 700 - index,
            }
        )

    other_oil_gas_count = 1773
    other_operator_count = 302
    for operator_index in range(other_operator_count):
        # 263 six-project groups and 39 five-project groups total 1,773 rows.
        count = 6 if operator_index < 263 else 5
        for project_index in range(count):
            row_index = len(definitions)
            definitions.append(
                {
                    "kind": "other_oil_gas",
                    "index": row_index,
                    "sector": "oil_gas",
                    "operator_number": f"9{operator_index:09d}",
                    "operator": f"A SCALE Synthetic Operator {operator_index:03d}",
                    "title": f"Synthetic Oil and Gas Project {operator_index:03d}-{project_index}",
                    "location": "Oklahoma" if project_index % 2 else "Texas",
                    "stage": "well_permitted" if project_index % 2 else "construction_started",
                    "rank": 600 - operator_index % 200,
                }
            )

    remaining = total_rows - len(definitions)
    if remaining != total_rows - (48 + 159 + 3 + 15 + other_oil_gas_count):
        raise AssertionError("scale fixture aggregate composition drifted")
    for index in range(remaining):
        definitions.append(
            {
                "kind": "other",
                "index": index,
                "sector": "other",
                "operator_number": None,
                "operator": None,
                "title": f"Synthetic Other Project {index:03d}",
                "location": "Oklahoma" if index % 3 else "Texas",
                "stage": "construction_started",
                "rank": 400 - index,
            }
        )

    project_ids = [uuid4() for _ in definitions]
    need_ids = [uuid4() for _ in definitions]
    source = Source(
        id=source_id,
        publisher="Synthetic fixture",
        endpoint="https://example.invalid/rollup-scale",
        family="construction-permits",
        geography="Synthetic",
        industries=["construction"],
        retrieval_method="socrata-permits",
        health={},
    )

    with factory.begin() as session:
        session.add(source)
        session.add_all([CompanyIdentity(id=value) for value in [*company_ids, *dc_customer_ids]])
        session.flush()

        # Core bulk inserts keep this test setup small and bypass unrelated
        # per-project qualification hooks while preserving canonical FKs.
        project_rows = []
        for index, (project_id, item) in enumerate(zip(project_ids, definitions, strict=True)):
            region = (
                classify_project_region(item["location"]) if item["kind"] == "de_central" else None
            )
            project_rows.append(
                {
                    "id": project_id,
                    "identity_key": f"synthetic-rollup-{generation_id}-{index}",
                    "name": item["title"],
                    "location": item["location"],
                    "source_id": source_id,
                    "external_id": str(index),
                    "asset_type": "synthetic",
                    "identity_facts": {},
                    "region_status": region.status if region else "HOLD",
                    "region_state": region.state if region else None,
                    "region_reason": region.reason if region else "synthetic_fixture_snapshot_only",
                    "region_provenance": (
                        region.provenance if region else {"synthetic_fixture": True}
                    ),
                }
            )
        session.execute(
            insert(Project.__table__),
            project_rows,
        )

        # Only the 48 DE CENTRAL projects need the canonical detail route for
        # the UI drill-down. Their evidence is explicitly synthetic and makes
        # no real site, operator, or power-demand claim.
        detail_observation_ids = [uuid4() for _ in range(48)]
        detail_evidence_ids = [uuid4() for _ in range(48)]
        detail_hashes = [
            hashlib.sha256(f"synthetic-detail-{generation_id}-{index}".encode()).hexdigest()
            for index in range(48)
        ]
        session.execute(
            insert(PowerNeed.__table__),
            [
                {
                    "id": need_ids[index],
                    "project_id": project_ids[index],
                    "activity_key": "synthetic-scale-activity",
                    "tier": "Signal",
                    "rationale": "Synthetic fixture only; no real power demand is asserted.",
                    "admission_basis": {},
                    "supply": "Unknown",
                    "active": True,
                    "updated_at": now,
                }
                for index in range(48)
            ],
        )
        session.execute(
            insert(Observation.__table__),
            [
                {
                    "id": detail_observation_ids[index],
                    "source_id": source_id,
                    "external_id": f"synthetic-detail-{generation_id}-{index}",
                    "title": definitions[index]["title"],
                    "abstract": (
                        "Synthetic integration-test record only. This content does not "
                        "describe an actual facility or power demand."
                    ),
                    "published_at": date(2026, 10, 1),
                    "url": f"https://example.invalid/rollup-scale/{index}",
                    "content_hash": detail_hashes[index],
                }
                for index in range(48)
            ],
        )
        session.execute(
            insert(Evidence.__table__),
            [
                {
                    "id": detail_evidence_ids[index],
                    "observation_id": detail_observation_ids[index],
                    "content_hash": detail_hashes[index],
                    "title": definitions[index]["title"],
                    "abstract": (
                        "Synthetic integration-test record only. This content does not "
                        "describe an actual facility or power demand."
                    ),
                    "url": f"https://example.invalid/rollup-scale/{index}",
                    "published_at": date(2026, 10, 1),
                    "observed_at": now,
                    "extraction_location": "synthetic fixture",
                    "provenance": {"synthetic_fixture": True},
                }
                for index in range(48)
            ],
        )
        session.execute(
            insert(Interpretation.__table__),
            [
                {
                    "observation_id": detail_observation_ids[index],
                    "content_hash": detail_hashes[index],
                    "evaluator_version": "synthetic-rollup-fixture-v1",
                    "assessment": {
                        "semantic_hash": detail_hashes[index],
                        "evidence_hash": detail_hashes[index],
                        "project_identity_key": f"synthetic-rollup-{generation_id}-{index}",
                        "power_activity": "synthetic-scale-activity",
                        "decision": "accepted",
                        "tier": "Signal",
                        "reason": "Synthetic fixture only; no real power demand is asserted.",
                        "subject": definitions[index]["title"],
                        "location": definitions[index]["location"],
                    },
                    "status": "accepted",
                    "attempts": 0,
                    "error": None,
                }
                for index in range(48)
            ],
        )
        session.execute(
            insert(NeedObservation.__table__),
            [
                {"need_id": need_ids[index], "observation_id": detail_observation_ids[index]}
                for index in range(48)
            ],
        )
        state = session.get(BrowseState, 1)
        if state is None:
            raise AssertionError("disposable test schema is missing its browse state row")
        session.add(
            BrowseGeneration(
                id=generation_id,
                input_revision=state.input_revision,
                policy_version=POLICY_VERSION,
                built_at=now,
                valid_from=now - timedelta(minutes=1),
                valid_until=now + timedelta(days=1),
                row_count=total_rows,
                digest=hashlib.sha256(f"synthetic-rollup-{generation_id}".encode()).hexdigest(),
                counts={"synthetic": True, "rows": total_rows},
            )
        )
        state.generation_id = generation_id
        session.flush()
        browse_rows = []
        memberships = []
        for index, (project_id, need_id, item) in enumerate(
            zip(project_ids, need_ids, definitions, strict=True)
        ):
            row_tier = "Signal" if item["kind"] == "de_central" else "Lead"
            metadata = {
                "sector": item["sector"],
                "title": item["title"],
                "operator": item["operator"],
                "event": {"kind": item["stage"], "source": "synthetic-fixture"},
            }
            if item["operator_number"]:
                metadata["oil_gas"] = {"operator_number": item["operator_number"]}
            if item["kind"] == "amazon":
                metadata["data_center"] = {"owner_developer": amazon_name}
                metadata["event"] = {
                    "kind": item["stage"],
                    "source": "texas-tdlr-tabs-data-centers",
                    "evidence_refs": [f"synthetic-tdlr-{item['index']}"],
                }
                memberships.append(
                    {
                        "generation_id": generation_id,
                        "company_identity_id": company_ids[item["index"]],
                        "project_id": project_id,
                        "organization_name": amazon_name,
                        "role": "owner_developer",
                        "supporting_evidence_count": 1,
                        "last_evidence_update": now,
                    }
                )
            elif item["kind"] == "dc_customer":
                memberships.append(
                    {
                        "generation_id": generation_id,
                        "company_identity_id": dc_customer_ids[item["company_index"]],
                        "project_id": project_id,
                        "organization_name": item["operator"],
                        "role": "owner_developer",
                        "supporting_evidence_count": 1,
                        "last_evidence_update": now,
                    }
                )
            compact = {
                "id": str(need_id),
                "project_id": str(project_id),
                "name": item["title"],
                "browse_title": item["title"],
                "location": item["location"],
                "activity": "synthetic construction",
                "tier": row_tier,
                "evidence_count": 1,
                "contact_actions": [],
                "contact_people": [],
                "project_metadata": metadata,
            }
            browse_rows.append(
                {
                    "generation_id": generation_id,
                    "need_id": need_id,
                    "project_id": project_id,
                    "tier": row_tier,
                    "location": item["location"],
                    "industry": item["sector"],
                    "activity": "synthetic construction",
                    "has_timing": False,
                    "mw_low": None,
                    "mw_high": None,
                    "priority_segment": 0,
                    "workflow_status": "open",
                    "signal_decision": "yes",
                    "project_group": "0" * 43,
                    "single_group": "0" * 43,
                    "rank_score": item["rank"],
                    "updated_at": now - timedelta(minutes=index),
                    "search_text": f"{item['title']} {item['operator'] or ''}".casefold(),
                    "display_title": item["title"],
                    "commercial_group": None,
                    "commercial_segment": None,
                    "commercial_geography": None,
                    "commercial_date": None,
                    "summary": {"synthetic_fixture": True},
                    "compact": compact,
                }
            )
        session.execute(insert(BrowseRow.__table__), browse_rows)
        if memberships:
            session.execute(insert(BrowseCustomerMembership.__table__), memberships)

    de_ids = project_ids[:48]
    diamond_ids = project_ids[48 : 48 + 159]
    amazon_ids = project_ids[48 + 159 : 48 + 159 + 3]
    return {
        "synthetic_fixture": True,
        "generation_id": str(generation_id),
        "total_rows": total_rows,
        "group_count": 417 + total_rows - 2098,
        "sector_counts": {
            "oil_gas": 1980,
            "data_centers": 18,
            "other": total_rows - 1998,
        },
        "groups": {
            "de_central": {
                "id": _group_id(f"rrc:{de_number}"),
                "name": "DE CENTRAL Synthetic Operator",
                "sector": "oil_gas",
                "operator_number": de_number,
                "project_count": 48,
                "project_ids": [str(value) for value in de_ids],
                "need_ids": [str(value) for value in need_ids[:48]],
                "search": "STORMCHASER",
                "filter_children": {
                    "search_project_id": str(de_ids[2]),
                    "region_project_id": str(de_ids[0]),
                    "stage_project_id": str(de_ids[1]),
                },
            },
            "diamondback": {
                "id": _group_id(f"rrc:{diamond_number}"),
                "name": "Diamondback Synthetic Operator",
                "sector": "oil_gas",
                "operator_number": diamond_number,
                "project_count": 159,
                "project_ids": [str(value) for value in diamond_ids],
                "need_ids": [str(value) for value in need_ids[48 : 48 + 159]],
            },
            "amazon": {
                "id": _group_id("namebucket:owner_developer:" + amazon_name.encode().hex()),
                "name": amazon_name,
                "sector": "data_centers",
                "project_count": 3,
                "identity_count": 3,
                "identity_ids": [str(value) for value in company_ids],
                "project_ids": [str(value) for value in amazon_ids],
                "need_ids": [str(value) for value in need_ids[48 + 159 : 48 + 159 + 3]],
            },
        },
        "other_data_center_project_count": 15,
        "other_data_center_identity_count": 12,
        "other_oil_gas_project_count": 1773,
    }
