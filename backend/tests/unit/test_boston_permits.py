from datetime import UTC, date, datetime

import httpx
import pytest

from gridlens.domain.commercial_presentation import commercial_size_status
from gridlens.domain.permit_interpretation import assess_permit
from gridlens.domain.permit_interpretation import evaluator_version as permit_evaluator_version
from gridlens.domain.signal_admission import admit_standalone, source_origin
from gridlens.ingestion.adapters.boston_permits import SOURCE_ID, retrieve
from gridlens.ingestion.adapters.federal_register import SourceParseError
from gridlens.ingestion.registry import load_registry


def source():
    return next(row for row in load_registry() if row["id"] == SOURCE_ID)


@pytest.mark.parametrize("lane", ["issue_recent", "issue_history"])
def test_daily_keyset_resumes_id_order_despite_reversed_issue_timestamps(lane):
    from gridlens.ingestion.adapters.boston_permits import retrieve_collection_segment

    day = date(2026, 10, 13)
    # Synthetic IDs cross the page boundary while their issue times go backwards.
    rows = [row(i, f"{day}T{23 - i % 24:02}:00:00") for i in range(1, 1002)]
    queries = []

    def handler(request):
        sql = request.url.params["sql"]
        queries.append(sql)
        if "COUNT(*)" in sql:
            result = [{"row_count": len(rows), "unique_permit_numbers": len(rows)}]
        else:
            assert "ORDER BY _id ASC LIMIT 1000" in sql
            assert "ORDER BY issued_date" not in sql
            result = rows[1000:] if "AND _id > 1000" in sql else rows[:1000]
        return httpx.Response(200, json={"success": True, "result": {"records": result}})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        first = retrieve_collection_segment(source(), lane, day, day, {}, client)
        assert first["cursor"]["after_id"] == 1000
        assert first["observed_count"] == 1000 and not first["window_complete"]
        resumed = retrieve_collection_segment(source(), lane, day, day, first["cursor"], client)
        replay = retrieve_collection_segment(source(), lane, day, day, first["cursor"], client)
    assert resumed == replay
    assert resumed["window_complete"] and resumed["observed_count"] == 1001
    assert resumed["records"][0]["document_number"] == "ALT1001"
    assert len({r["document_number"] for r in first["records"] + resumed["records"]}) == 1001


@pytest.mark.parametrize("bad_rows", [[2, 1], [1, 1]])
def test_daily_keyset_rejects_duplicate_or_descending_rows(bad_rows):
    from gridlens.ingestion.adapters.boston_permits import retrieve_collection_segment

    day = date(2026, 10, 13)

    def handler(request):
        records = (
            [{"row_count": 2, "unique_permit_numbers": 2}]
            if "COUNT(*)" in request.url.params["sql"]
            else [row(i, f"{day}T00:00:00") for i in bad_rows]
        )
        return httpx.Response(200, json={"success": True, "result": {"records": records}})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(SourceParseError, match="duplicate identity or bad order"):
            retrieve_collection_segment(source(), "issue_recent", day, day, {}, client)


def row(row_id: int, issued: str, **updates):
    result = {
        "_id": row_id,
        "permitnumber": f"ALT{row_id}",
        "worktype": "INTEXT",
        "permittypedescr": "Long Form Permit",
        "description": "New data center construction",
        "comments": "Construct data center",
        "applicant": "Example Applicant LLC",
        "issued_date": issued,
        "expiration_date": None,
        "status": "Open",
        "occupancytype": "Comm",
        "address": "1 Industry Way",
        "city": "Boston",
        "state": "MA",
        "declared_valuation": "$100,000.00",
        "sq_feet": 10000,
        "property_id": 11,
        "parcel_id": 12,
    }
    return result | updates


def test_registry_is_bounded_and_enabled_only_for_verified_official_host():
    definition = source()
    assert definition["enabled"] is False
    assert definition["query"]["window_days"] == 90
    assert definition["endpoint"] == "https://data.boston.gov/api/3/action/datastore_search_sql"
    assert source_origin(definition["family"], definition["retrieval_method"]) == "Official permit"
    admission = admit_standalone(
        source_id=SOURCE_ID,
        family=definition["family"],
        retrieval_method=definition["retrieval_method"],
        accepted=True,
        activity="facility-expansion",
        title="Boston building permit",
        abstract="",
    )
    assert admission.admitted


def test_recent_permits_are_count_checked_ordered_and_roles_stay_unknown():
    today = datetime.now(UTC).date()
    first = row(5, f"{today.isoformat()}T01:00:00")
    second = row(
        6,
        f"{today.isoformat()}T02:00:00",
        permittypedescr="Amendment to a Long Form",
        comments="This work is to Amend Permit ALT10001",
    )
    requests = []

    def handler(request):
        sql = request.url.params["sql"]
        requests.append(sql)
        if "COUNT(*)" in sql:
            return httpx.Response(
                200, json={"success": True, "result": {"records": [{"row_count": 2}]}}
            )
        rows = [first, second] if "OFFSET 0" in sql else []
        return httpx.Response(200, json={"success": True, "result": {"records": rows}})

    result = retrieve(source(), httpx.Client(transport=httpx.MockTransport(handler)))
    assert [record["document_number"] for record in result] == ["ALT5", "ALT6"]
    assert result[1]["permit"]["amendment_of"] == "ALT10001"
    assert result[0]["permit"]["applicant_role"] == "applicant"
    assert result[0]["permit"]["buyer_role"] == "UNKNOWN"
    assert "filters=%7B%22permitnumber%22%3A%22ALT5%22%7D" in result[0]["html_url"]
    assert "Applicant (buying role unknown)" in result[0]["abstract"]
    assert "valuation" not in result[0]["permit"]
    assert "issued_date ASC, _id ASC LIMIT 1000 OFFSET 0" in requests[1]
    assert "issued_date >= " in requests[0] and "issued_date <= " in requests[0]
    assert requests[-1] == requests[0]


def test_closed_permits_are_retained_but_not_admitted_and_current_status_is_preserved():
    assessment = assess_permit(
        {
            "event_date": datetime.now(UTC).date().isoformat(),
            "html_url": "https://data.boston.gov/api/3/action/datastore_search_sql",
            "permit": {
                "source_type": "boston-building-permits",
                "row_id": "12",
                "address": "1 Industry Way",
                "city": "Boston",
                "state": "MA",
                "description": "Construct new data center",
                "status": "Closed",
                "class": "Comm",
                "source_fields": {"description": "description"},
            },
        }
    )
    assert assessment["decision"] == "rejected"
    assert assessment["permit_status"] == "Closed"


def test_open_boston_permit_can_be_a_signal_without_claiming_rental_need_or_mw():
    assessment = assess_permit(
        {
            "event_date": datetime.now(UTC).date().isoformat(),
            "html_url": "https://data.boston.gov/api/3/action/datastore_search?resource_id=x",
            "permit": {
                "source_type": "boston-building-permits",
                "row_id": "13",
                "address": "1 Industry Way",
                "city": "Boston",
                "state": "MA",
                "description": "Construct new data center",
                "status": "Open",
                "class": "Comm",
                "source_fields": {"description": "description"},
            },
        }
    )
    assert assessment["decision"] == "accepted"
    assert assessment["tier"] == "Signal"
    assert assessment["permit_status"] == "Open"
    assert "does not prove work start" in assessment["reason"]
    assert "does not prove work start" in assessment["reason"]
    assert "activity-specific power requirement" in assessment["missing_facts"]


def test_temporary_generator_rating_is_reported_as_source_context_without_aggregation():
    quote = (
        "Generators Installation of (2) 375KW temporary generator to back up building "
        "while permanent generator is serviced."
    )
    assessment = assess_permit(
        {
            "event_date": datetime.now(UTC).date().isoformat(),
            "html_url": "https://data.boston.gov/api/3/action/datastore_search?resource_id=x",
            "permit": {
                "source_type": "boston-building-permits",
                "row_id": "ETS1895395",
                "address": "1 Industry Way",
                "city": "Boston",
                "state": "MA",
                "description": quote,
                "status": "Open",
                "class": "Comm",
                "source_fields": {"description": "description"},
            },
        }
    )
    assert assessment["reported_power_facts"] == [quote]
    assert permit_evaluator_version({"permit": {"source_type": "boston-building-permits"}})
    assert permit_evaluator_version({"permit": {"source_type": "boston-building-permits"}}) == (
        "boston-permit-power-facts-v1"
    )
    assert "required_mw" not in assessment
    assert (
        commercial_size_status(
            None,
            assessment["power_activity"],
            assessment["action"],
            assessment["reported_power_facts"],
        )
        == "at_or_above_floor"
    )


def test_explicit_small_temporary_generator_rating_is_below_floor():
    quote = "Install one 35kW temporary generator for construction service."
    assessment = assess_permit(
        {
            "event_date": datetime.now(UTC).date().isoformat(),
            "html_url": "https://data.boston.gov/api/3/action/datastore_search?resource_id=x",
            "permit": {
                "source_type": "boston-building-permits",
                "row_id": "ETS35KW",
                "address": "1 Industry Way",
                "city": "Boston",
                "state": "MA",
                "description": quote,
                "status": "Open",
            },
        }
    )
    assert assessment["reported_power_facts"] == [quote]
    assert (
        commercial_size_status(
            None,
            assessment["power_activity"],
            assessment["action"],
            assessment["reported_power_facts"],
        )
        == "below_floor"
    )


@pytest.mark.parametrize(
    "quote",
    [
        "Install a 400 amp temporary generator.",
        "Install a 400 kVA temporary generator.",
        "Site utility load is 2 MW. Install a temporary generator.",
    ],
)
def test_unrecognized_generator_units_stay_unknown(quote):
    assessment = assess_permit(
        {
            "event_date": datetime.now(UTC).date().isoformat(),
            "html_url": "https://data.boston.gov/api/3/action/datastore_search?resource_id=x",
            "permit": {
                "source_type": "boston-building-permits",
                "row_id": "ETSUNKNOWN",
                "address": "1 Industry Way",
                "city": "Boston",
                "state": "MA",
                "description": quote,
                "status": "Open",
            },
        }
    )
    assert assessment["reported_power_facts"] == []
    assert (
        commercial_size_status(
            None,
            assessment["power_activity"],
            assessment["action"],
            assessment["reported_power_facts"],
        )
        == "unknown"
    )


def test_campus_nameplate_qualifier_is_preserved_and_not_mistaken_for_rental_need():
    quote = (
        "Campus nameplate capacity is 80 MW. Generators Installation of (2) 375KW "
        "temporary generator to back up building while permanent generator is serviced."
    )
    assessment = assess_permit(
        {
            "event_date": datetime.now(UTC).date().isoformat(),
            "html_url": "https://data.boston.gov/api/3/action/datastore_search?resource_id=x",
            "permit": {
                "source_type": "boston-building-permits",
                "row_id": "ETSQUALIFIER",
                "address": "1 Industry Way",
                "city": "Boston",
                "state": "MA",
                "description": quote,
                "status": "Open",
            },
        }
    )
    assert assessment["reported_power_facts"] == [quote]
    assert "Campus nameplate capacity is 80 MW" in assessment["reported_power_facts"][0]
    assert (
        commercial_size_status(
            None,
            assessment["power_activity"],
            assessment["action"],
            assessment["reported_power_facts"],
        )
        == "unknown"
    )


def test_reindex_keeps_permit_observation_identity_and_hash_but_semantic_change_versions_it():
    item = row(5, f"{datetime.now(UTC).date().isoformat()}T10:00:00")

    def retrieve_one():
        def handler(request):
            sql = request.url.params["sql"]
            rows = [{"row_count": 1}] if "COUNT(*)" in sql else [dict(item)]
            return httpx.Response(200, json={"success": True, "result": {"records": rows}})

        return retrieve(source(), httpx.Client(transport=httpx.MockTransport(handler)))[0]

    original = retrieve_one()
    item["_id"] = 8005
    reindexed = retrieve_one()
    assert reindexed["document_number"] == original["document_number"] == "ALT5"
    assert reindexed["source_hash"] == original["source_hash"]
    assert reindexed["permit"]["raw_source_row_id"] == "8005"
    item["status"] = "Closed"
    changed = retrieve_one()
    assert changed["document_number"] == original["document_number"]
    assert changed["source_hash"] != original["source_hash"]
    assert changed["permit"]["status"] == "Closed"


@pytest.mark.parametrize(
    "mutation", ["duplicate", "duplicate_permitnumber", "out_of_window", "count_changes"]
)
def test_inconsistent_or_escaped_rows_fail_closed(mutation):
    today = datetime.now(UTC).date()
    item = row(1, f"{today.isoformat()}T10:00:00")
    count_calls = 0

    def handler(request):
        nonlocal count_calls
        sql = request.url.params["sql"]
        if "COUNT(*)" in sql:
            count_calls += 1
            count = (
                2
                if mutation == "duplicate_permitnumber"
                or mutation == "count_changes"
                and count_calls == 1
                else 1
            )
            return httpx.Response(
                200, json={"success": True, "result": {"records": [{"row_count": count}]}}
            )
        rows = (
            [item, item]
            if mutation == "duplicate"
            else [item, row(2, item["issued_date"], permitnumber=item["permitnumber"])]
            if mutation == "duplicate_permitnumber"
            else [item]
        )
        if mutation == "out_of_window":
            rows[0] = row(1, "2020-01-01T00:00:00")
        return httpx.Response(200, json={"success": True, "result": {"records": rows}})

    with pytest.raises(SourceParseError):
        retrieve(source(), httpx.Client(transport=httpx.MockTransport(handler)))
