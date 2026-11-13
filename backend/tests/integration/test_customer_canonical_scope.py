"""Canonical company scope for the default Opportunities customer directory."""

import pytest
from fastapi import HTTPException
from sqlalchemy import select
from starlette.requests import Request

from gridlens.api.app import _validate_browse_query
from gridlens.intelligence.customer_results import (
    group_metadata,
    group_open,
    group_projects,
    groups,
)
from gridlens.intelligence.saved_browse import current_generation
from gridlens.persistence.models import BrowseRow, Project

pytest_plugins = ["test_saved_browse"]


def _seed_group_cohort(factory):
    from test_customer_results import _seed_group_cohort as seed

    return seed(factory)


def _seed_tdlr_name_bucket(factory):
    from test_customer_results import _seed_tdlr_name_bucket as seed

    return seed(factory)


def _browse_request(path):
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": path,
            "root_path": "",
            "scheme": "http",
            "query_string": b"canonical_only=true",
            "headers": [],
            "server": ("test", 80),
            "client": ("test", 123),
        }
    )


@pytest.mark.parametrize(
    "path",
    [
        "/api/opportunities/groups",
        "/api/opportunities/groups/cg_example/projects",
        "/api/opportunities/groups/cg_example/open",
    ],
)
def test_canonical_query_flag_is_limited_to_customer_group_routes(path):
    _validate_browse_query(_browse_request(path))
    with pytest.raises(HTTPException) as unsupported:
        _validate_browse_query(_browse_request("/api/opportunities/projects"))
    assert unsupported.value.status_code == 422


def test_canonical_scope_filters_groups_before_totals_and_child_reads(saved_db):
    generation_id = _seed_group_cohort(saved_db)
    with saved_db.begin() as session:
        generation = current_generation(session)
        assert str(generation.id) == str(generation_id)
        unresolved_project = session.scalar(select(Project).where(Project.external_id == "62"))
        rows = session.scalars(
            select(BrowseRow).where(
                BrowseRow.generation_id == generation.id,
                BrowseRow.project_id == unresolved_project.id,
            )
        ).all()
        for row in rows:
            row.compact = {
                **row.compact,
                "location": "Unresolved Only Region",
                "project_metadata": {
                    **row.compact["project_metadata"],
                    "event": {"kind": "unresolved_only_stage"},
                },
            }
    with saved_db() as session:
        legacy = groups(session, sector="oil_gas", limit=100)
        canonical = groups(session, sector="oil_gas", limit=100, canonical_only=True)
        assert legacy["total"] > canonical["total"]
        assert legacy["cohort_token"] != canonical["cohort_token"]
        assert all(item["group_kind"] == "resolved_identity" for item in canonical["items"])
        assert canonical["total"] == canonical["totals"]["accounts"]
        # RRC-only operator identity is canonical even without a company UUID or
        # an eligible commercial Need; identity scope must not be eligibility scope.
        no_eligible = next(item for item in canonical["items"] if item["eligible_need_count"] == 0)
        assert no_eligible["group_kind"] == "resolved_identity"

        first = groups(session, sector="oil_gas", limit=1, canonical_only=True)
        empty = groups(
            session,
            sector="oil_gas",
            limit=1,
            offset=first["total"],
            token=first["cohort_token"],
            canonical_only=True,
        )
        assert empty["items"] == []
        assert empty["total"] == first["total"]
        assert empty["totals"] == first["totals"]
        assert set(canonical["facets"]["regions"]).issubset(set(legacy["facets"]["regions"]))
        assert "Unresolved Only Region" in legacy["facets"]["regions"]
        assert "Unresolved Only Region" not in canonical["facets"]["regions"]
        assert "unresolved_only_stage" not in canonical["facets"]["stages"]

        with pytest.raises(HTTPException) as cross_parent:
            groups(
                session,
                sector="oil_gas",
                limit=1,
                offset=1,
                token=first["cohort_token"],
            )
        assert cross_parent.value.status_code == 409

        group_id = no_eligible["id"]
        opened = group_open(session, group_id, sector="oil_gas", canonical_only=True)
        metadata = group_metadata(session, group_id, sector="oil_gas", canonical_only=True)
        assert opened["group"]["id"] == metadata["id"] == group_id
        assert opened["projects"]["items"]
        children = group_projects(
            session,
            group_id,
            sector="oil_gas",
            canonical_only=True,
            parent_token=canonical["cohort_token"],
        )
        assert children["total"] == metadata["project_count"]
        with pytest.raises(HTTPException) as cross_child:
            group_projects(
                session,
                group_id,
                sector="oil_gas",
                canonical_only=True,
                parent_token=canonical["cohort_token"],
                offset=1,
            )
        assert cross_child.value.status_code == 422
        with pytest.raises(HTTPException) as crossing_mode:
            group_projects(
                session,
                group_id,
                sector="oil_gas",
                parent_token=canonical["cohort_token"],
                offset=1,
                token=children["cohort_token"],
            )
        assert crossing_mode.value.status_code == 409


def test_same_name_unconfirmed_group_is_only_in_legacy_scope(saved_db):
    _seed_tdlr_name_bucket(saved_db)
    with saved_db() as session:
        legacy = groups(session, sector="data_centers", limit=25)
        bucket = next(
            item for item in legacy["items"] if item["group_kind"] == "same_name_unconfirmed"
        )
        canonical = groups(session, sector="data_centers", limit=25, canonical_only=True)
        assert bucket["id"] not in {item["id"] for item in canonical["items"]}
        search_canonical = groups(
            session, search="AMAZON DATA SERVICES", sector="data_centers", canonical_only=True
        )
        assert bucket["id"] not in {item["id"] for item in search_canonical["items"]}
        assert all(item["group_kind"] == "resolved_identity" for item in search_canonical["items"])
        # False preserves the provisional bucket and its project page contract.
        legacy_children = group_projects(
            session,
            bucket["id"],
            sector="data_centers",
            parent_token=legacy["cohort_token"],
        )
        assert legacy_children["total"] == bucket["project_count"]
        assert (
            group_open(session, bucket["id"], sector="data_centers")["group"]["id"] == bucket["id"]
        )
        assert group_metadata(session, bucket["id"], sector="data_centers")["id"] == bucket["id"]
        assert all(item["group_kind"] == "resolved_identity" for item in canonical["items"])
        for loader in (group_open, group_metadata):
            with pytest.raises(HTTPException) as missing:
                loader(session, bucket["id"], sector="data_centers", canonical_only=True)
            assert missing.value.status_code == 404
        with pytest.raises(HTTPException) as hidden_child:
            group_projects(
                session,
                bucket["id"],
                sector="data_centers",
                canonical_only=True,
                parent_token=canonical["cohort_token"],
            )
        assert hidden_child.value.status_code == 404
        # Default mode retains the exact historical membership token.
        legacy_again = groups(session, sector="data_centers", limit=25)
        assert legacy_again["cohort_token"] == legacy["cohort_token"]
