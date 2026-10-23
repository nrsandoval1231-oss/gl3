import time
from datetime import date
from typing import Any

import httpx

from gridlens.ingestion.adapters.boston_permits import retrieve as retrieve_boston_permits
from gridlens.ingestion.adapters.bounded_http import run_isolated
from gridlens.ingestion.adapters.cabq_building_permits import retrieve as retrieve_cabq_permits
from gridlens.ingestion.adapters.ceqanet import retrieve as retrieve_ceqanet
from gridlens.ingestion.adapters.dallas_permits import retrieve as retrieve_dallas_permits
from gridlens.ingestion.adapters.el_paso_permits import retrieve as retrieve_el_paso_permits
from gridlens.ingestion.adapters.federal_register import SourceParseError
from gridlens.ingestion.adapters.fort_worth_permits import retrieve as retrieve_fort_worth_permits
from gridlens.ingestion.adapters.georgia_air_permits import retrieve as retrieve_georgia_air_permits
from gridlens.ingestion.adapters.houston_permits import retrieve as retrieve_houston_permits
from gridlens.ingestion.adapters.ma_cultivation import retrieve as retrieve_ma_cultivation
from gridlens.ingestion.adapters.nc_commerce import retrieve as retrieve_nc_commerce
from gridlens.ingestion.adapters.ok_deq_public_review import retrieve as retrieve_ok_deq
from gridlens.ingestion.adapters.publisher_rss import retrieve as retrieve_publisher_rss
from gridlens.ingestion.adapters.rrc_flare_exceptions import (
    retrieve as retrieve_rrc_flare_exceptions,
)
from gridlens.ingestion.adapters.san_antonio_permits import (
    retrieve as retrieve_san_antonio_permits,
)
from gridlens.ingestion.adapters.socrata_permits import retrieve as retrieve_socrata_permits
from gridlens.ingestion.adapters.spp_interconnection import retrieve as retrieve_spp_queue
from gridlens.ingestion.adapters.taylor_newsflash import retrieve as retrieve_taylor_newsflash
from gridlens.ingestion.adapters.tceq_nsr_pending import retrieve as retrieve_tceq_nsr_pending
from gridlens.ingestion.adapters.tceq_temporary_batch import (
    retrieve as retrieve_tceq_temporary_batch,
)
from gridlens.ingestion.adapters.tdlr_tabs import retrieve as retrieve_tdlr_tabs


def retrieve_source(
    source: dict[str, Any],
    client: httpx.Client | None = None,
    *,
    deadline: float | None = None,
    request_headers: dict[str, str] | None = None,
) -> list[dict[str, Any]] | dict[str, Any]:
    if client is None:
        absolute_deadline = deadline or time.monotonic() + 25.0
        return run_isolated(
            "gridlens.ingestion.adapters:_retrieve_source_direct",
            (source, None, request_headers, absolute_deadline),
            {},
            deadline=absolute_deadline,
        )
    return _retrieve_source_direct(source, client, request_headers, deadline)


def _retrieve_source_direct(
    source: dict[str, Any],
    client: httpx.Client | None = None,
    request_headers: dict[str, str] | None = None,
    deadline: float | None = None,
) -> list[dict[str, Any]] | dict[str, Any]:
    method = source.get("retrieval_method")
    if method in {"federal-register-json", "json-api"}:
        from gridlens.ingestion.adapters.federal_register import retrieve

        return retrieve(source, client)
    if method == "nc-commerce-html":
        return retrieve_nc_commerce(source, client)
    if method == "publisher-rss":
        if client is None and request_headers:
            with httpx.Client(
                timeout=25.0, follow_redirects=False, headers=request_headers
            ) as rss_client:
                return retrieve_publisher_rss(source, rss_client, deadline=deadline)
        return retrieve_publisher_rss(source, client, deadline=deadline)
    if method == "rrc-drilling-permits":
        from gridlens.ingestion.adapters.rrc_drilling import retrieve

        return retrieve(source, client)
    if method == "rrc-flare-exceptions":
        return retrieve_rrc_flare_exceptions(source, client)
    if method == "houston-weekly-permits":
        return retrieve_houston_permits(source, client)
    if method == "dallas-monthly-permits":
        return retrieve_dallas_permits(source, client)
    if method == "el-paso-new-commercial-permits":
        return retrieve_el_paso_permits(source, client)
    if method == "socrata-permits":
        return retrieve_socrata_permits(source, client)
    if method == "boston-ckan-permits":
        return retrieve_boston_permits(source, client)
    if method == "georgia-air-permits":
        return retrieve_georgia_air_permits(source, client)
    if method == "ma-cultivation-applications":
        return retrieve_ma_cultivation(source, client)
    if method == "tdlr-tabs":
        return retrieve_tdlr_tabs(source, client)
    if method == "san-antonio-permits":
        return retrieve_san_antonio_permits(source, client)
    if method == "fort-worth-permits":
        return retrieve_fort_worth_permits(source, client)
    if method == "ceqanet-data-centers":
        return retrieve_ceqanet(source, client)
    if method == "tceq-temporary-batch-plants":
        return retrieve_tceq_temporary_batch(source, client)
    if method == "tceq-nsr-pending":
        return retrieve_tceq_nsr_pending(source, client)
    if method == "taylor-newsflash":
        return retrieve_taylor_newsflash(source, client)
    if method == "ok-deq-public-review":
        return retrieve_ok_deq(source, client)
    if method == "spp-interconnection-queue":
        return retrieve_spp_queue(source, client)
    if method == "cabq-building-permits":
        return retrieve_cabq_permits(source, client)
    raise SourceParseError(f"Unsupported source retrieval method: {method}")


def retrieve_collection_segment(
    source: dict[str, Any],
    lane: str,
    window_start: date,
    window_end: date,
    cursor: dict[str, Any],
    client: httpx.Client | None = None,
    *,
    deadline: float | None = None,
) -> dict[str, Any]:
    """Run one resumable structured-source segment in the bounded fetch child."""
    if client is not None:
        return _retrieve_collection_segment_direct(
            source, lane, window_start.isoformat(), window_end.isoformat(), cursor, client
        )
    absolute_deadline = deadline or time.monotonic() + 25.0
    return run_isolated(
        "gridlens.ingestion.adapters:_retrieve_collection_segment_direct",
        (source, lane, window_start.isoformat(), window_end.isoformat(), cursor, None),
        {},
        deadline=absolute_deadline,
    )


def _retrieve_collection_segment_direct(
    source: dict[str, Any],
    lane: str,
    window_start: str,
    window_end: str,
    cursor: dict[str, Any],
    client: httpx.Client | None = None,
) -> dict[str, Any]:
    start, end = date.fromisoformat(window_start), date.fromisoformat(window_end)
    method = source.get("retrieval_method")
    if method == "socrata-permits":
        from gridlens.ingestion.adapters.socrata_permits import retrieve_collection_segment

        return retrieve_collection_segment(source, lane, start, end, cursor, client)
    if method == "boston-ckan-permits":
        from gridlens.ingestion.adapters.boston_permits import retrieve_collection_segment

        return retrieve_collection_segment(source, lane, start, end, cursor, client)
    raise SourceParseError("Source has no resumable structured collection adapter")


def retrieve_companion(
    record: dict[str, Any],
    client: httpx.Client | None = None,
    *,
    deadline: float | None = None,
) -> list[dict[str, str]]:
    """Retrieve/parse a bounded companion document outside the parent process."""
    absolute_deadline = deadline or time.monotonic() + 30.0
    if client is not None:
        from gridlens.ingestion.adapters.govinfo_pdf import retrieve_companion as direct

        return direct(record, client, deadline=absolute_deadline)
    return run_isolated(
        "gridlens.ingestion.adapters:_retrieve_companion_direct",
        (record, absolute_deadline),
        {},
        deadline=absolute_deadline,
    )


def _retrieve_companion_direct(record: dict[str, Any], deadline: float) -> list[dict[str, str]]:
    from gridlens.ingestion.adapters.govinfo_pdf import retrieve_companion as direct

    return direct(record, deadline=deadline)
