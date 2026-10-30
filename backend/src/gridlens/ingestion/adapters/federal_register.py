import json
from datetime import date, timedelta
from typing import Any
from urllib.parse import urlsplit

import httpx

from gridlens.ingestion.adapters.bounded_http import ResponseTooLarge, read_bounded_response


class SourceParseError(ValueError):
    pass


_FERC_EIS_SOURCE_ID = "federal-register-eis"
_FEDERAL_REGISTER_ENDPOINT = "https://www.federalregister.gov/api/v1/documents.json"


def _canonical_key(record: dict[str, Any]) -> str:
    try:
        return json.dumps(record, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    except (TypeError, ValueError) as exc:
        raise SourceParseError("Federal Register record was not canonical JSON") from exc


def _validate_query(source: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, str]]]:
    query = source.get("query")
    if not isinstance(query, dict):
        raise SourceParseError("Federal Register query configuration is invalid")
    required = {
        "term",
        "document_type",
        "window_days",
        "per_page",
        "max_pages",
        "max_response_bytes",
        "max_run_bytes",
    }
    optional = {"supplemental_queries"}
    if not required <= query.keys() or query.keys() - required - optional:
        raise SourceParseError("Federal Register query fields are invalid")
    if (
        not isinstance(query["term"], str)
        or not query["term"].strip()
        or not isinstance(query["document_type"], str)
        or not query["document_type"].strip()
    ):
        raise SourceParseError("Federal Register search term or document type is invalid")
    for key in ("window_days", "per_page", "max_pages", "max_response_bytes", "max_run_bytes"):
        if type(query[key]) is not int:
            raise SourceParseError(f"Federal Register {key} must be an integer")
    if not 1 <= query["window_days"] <= 90:
        raise SourceParseError("Federal Register date window is invalid")
    if query["per_page"] != 100:
        raise SourceParseError("Federal Register page size is invalid")
    if not 1 <= query["max_pages"] <= 10:
        raise SourceParseError("Federal Register page bound is invalid")
    if (
        not 1024 <= query["max_response_bytes"] <= 5_000_000
        or not query["max_response_bytes"] <= query["max_run_bytes"] <= 100_000_000
    ):
        raise SourceParseError("Federal Register response-byte bounds are invalid")

    supplemental = query.get("supplemental_queries", [])
    if "supplemental_queries" in query:
        endpoint = source.get("endpoint")
        if source.get("id") != _FERC_EIS_SOURCE_ID:
            raise SourceParseError(
                "Supplemental Federal Register searches are not enabled for this source"
            )
        if endpoint != _FEDERAL_REGISTER_ENDPOINT:
            raise SourceParseError(
                "Supplemental Federal Register searches require the reviewed JSON API endpoint"
            )
        endpoint_parts = urlsplit(endpoint)
        if (
            source.get("retrieval_method") != "json-api"
            or endpoint_parts.scheme != "https"
            or endpoint_parts.netloc != "www.federalregister.gov"
            or endpoint_parts.path != "/api/v1/documents.json"
            or endpoint_parts.query
            or endpoint_parts.fragment
        ):
            raise SourceParseError(
                "Supplemental Federal Register searches require the reviewed JSON API endpoint"
            )
    if not isinstance(supplemental, list) or len(supplemental) > 1:
        raise SourceParseError("Federal Register supplemental queries are invalid")
    if supplemental:
        lane = supplemental[0]
        if (
            not isinstance(lane, dict)
            or set(lane) != {"term", "agency"}
            or lane.get("term") != "environmental assessment"
            or lane.get("agency") != "federal-energy-regulatory-commission"
        ):
            raise SourceParseError("Federal Register supplemental query is unsupported")
    return query, supplemental


def _page_payload(content: bytes, *, lane: str, page: int) -> dict[str, Any]:
    try:
        payload = json.loads(content)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise SourceParseError("Federal Register response was not valid JSON") from exc
    if not isinstance(payload, dict):
        raise SourceParseError(f"Federal Register {lane} page {page} schema invalid")
    results = payload.get("results")
    count = payload.get("count")
    total_pages = payload.get("total_pages")
    if (
        not isinstance(results, list)
        or type(count) is not int
        or count < 0
        or type(total_pages) is not int
        or total_pages < 0
    ):
        raise SourceParseError(f"Federal Register {lane} page {page} schema invalid")
    if count == 0:
        if results or total_pages not in (0, 1):
            raise SourceParseError(f"Unexpected empty or malformed {lane} query")
    elif total_pages < 1 or not results:
        raise SourceParseError(f"Unexpected empty or malformed {lane} page {page}")
    return payload


def retrieve(
    source: dict[str, Any],
    client: httpx.Client | None = None,
    *,
    deadline: float | None = None,
) -> list[dict[str, Any]]:
    query, supplemental = _validate_query(source)
    lanes: list[tuple[str, dict[str, str]]] = [("primary", {"term": query["term"]})]
    lanes.extend(("supplemental", lane) for lane in supplemental)
    if len(lanes) > query["max_pages"]:
        raise SourceParseError("Federal Register page bound cannot cover all query probes")

    own_client = client is None
    client = client or httpx.Client(timeout=25.0, follow_redirects=False)

    today = date.today()
    start = today - timedelta(days=query["window_days"])
    common: dict[str, str | int] = {
        "conditions[type][]": query["document_type"],
        "conditions[publication_date][gte]": start.isoformat(),
        "conditions[publication_date][lte]": today.isoformat(),
        "order": "newest",
        "per_page": query["per_page"],
    }
    response_limit = query["max_response_bytes"]
    run_limit = query["max_run_bytes"]
    bytes_seen = 0
    requests_seen = 0
    plans: list[dict[str, Any]] = []

    def get_page(params: dict[str, str | int], lane_name: str, page: int) -> dict[str, Any]:
        nonlocal bytes_seen, requests_seen
        if requests_seen >= query["max_pages"]:
            raise SourceParseError("Federal Register queries exceed the shared page bound")
        remaining_run_bytes = run_limit - bytes_seen
        if remaining_run_bytes <= 0:
            raise SourceParseError("Federal Register response bytes exceed the run bound")
        try:
            _, content = read_bounded_response(
                client,
                source["endpoint"],
                min(response_limit, remaining_run_bytes),
                {**params, "page": page},
                deadline=deadline,
            )
        except ResponseTooLarge as exc:
            raise SourceParseError(str(exc)) from exc
        requests_seen += 1
        bytes_seen += len(content)
        return _page_payload(content, lane=lane_name, page=page)

    try:
        # Probe page one for every lane before following any pagination cursor.
        for lane_name, lane in lanes:
            params = {**common, "conditions[term]": lane["term"]}
            if "agency" in lane:
                params["conditions[agencies][]"] = lane["agency"]
            first = get_page(params, lane_name, 1)
            plans.append(
                {
                    "name": lane_name,
                    "params": params,
                    "first": first,
                    "pages": first["total_pages"],
                    "count": first["count"],
                    "results": list(first["results"]),
                }
            )

        required_requests = sum(max(plan["pages"], 1) for plan in plans)
        if required_requests > query["max_pages"]:
            raise SourceParseError(
                f"Federal Register query lanes require {required_requests} pages; "
                f"shared maximum is {query['max_pages']}"
            )

        for plan in plans:
            if plan["count"] == 0:
                continue
            first = plan["first"]
            if first["total_pages"] < 1 or first["total_pages"] > query["max_pages"]:
                raise SourceParseError(
                    f"Bounded {plan['name']} query requires {first['total_pages']} pages"
                )
            for page in range(2, plan["pages"] + 1):
                payload = get_page(plan["params"], plan["name"], page)
                if payload["count"] != plan["count"] or payload["total_pages"] != plan["pages"]:
                    raise SourceParseError(
                        f"Federal Register {plan['name']} pagination metadata changed"
                    )
                if not payload["results"]:
                    raise SourceParseError(
                        f"Unexpected empty Federal Register {plan['name']} page {page}"
                    )
                plan["results"].extend(payload["results"])

        records: list[dict[str, Any]] = []
        seen_canonical: set[str] = set()
        for plan in plans:
            rendered: list[dict[str, Any]] = [render_record(row) for row in plan["results"]]
            if len(rendered) != plan["count"]:
                raise SourceParseError(f"Federal Register {plan['name']} pagination was incomplete")
            lane_keys = [_canonical_key(row) for row in rendered]
            if len(lane_keys) != len(set(lane_keys)):
                raise SourceParseError(
                    f"Federal Register {plan['name']} repeated an identical record"
                )
            for record, key in zip(rendered, lane_keys, strict=True):
                if key not in seen_canonical:
                    records.append(record)
                    seen_canonical.add(key)
        return records
    finally:
        if own_client:
            client.close()


def render_record(row: dict[str, Any]) -> dict[str, Any]:
    """The same retained fields for paged ingestion and one-document refresh."""
    required = ("document_number", "title", "publication_date", "html_url")
    if not isinstance(row, dict) or any(not row.get(key) for key in required):
        raise SourceParseError("Federal Register record missing required fields")
    try:
        date.fromisoformat(row["publication_date"])
    except (TypeError, ValueError) as exc:
        raise SourceParseError("Federal Register record has an invalid publication date") from exc
    return {
        key: row.get(key)
        for key in (
            "document_number",
            "title",
            "abstract",
            "publication_date",
            "html_url",
            "pdf_url",
        )
    }
