import json
from datetime import date, timedelta
from typing import Any

import httpx

from gridlens.ingestion.adapters.bounded_http import ResponseTooLarge, read_bounded_response


class SourceParseError(ValueError):
    pass


def retrieve(source: dict[str, Any], client: httpx.Client | None = None) -> list[dict[str, Any]]:
    own_client = client is None
    client = client or httpx.Client(timeout=25.0, follow_redirects=False)
    query = source["query"]
    today = date.today()
    start = today - timedelta(days=query["window_days"])
    base: dict[str, str | int] = {
        "conditions[term]": query["term"],
        "conditions[type][]": query["document_type"],
        "conditions[publication_date][gte]": start.isoformat(),
        "conditions[publication_date][lte]": today.isoformat(),
        "order": "newest",
        "per_page": query["per_page"],
    }
    records: list[dict[str, Any]] = []
    max_response_bytes = query.get("max_response_bytes", 4_000_000)
    max_run_bytes = query.get("max_run_bytes", 20_000_000)
    if (
        not isinstance(max_response_bytes, int)
        or not isinstance(max_run_bytes, int)
        or max_response_bytes < 1024
        or max_response_bytes > max_run_bytes
        or max_run_bytes > 100_000_000
    ):
        raise SourceParseError("Federal Register response-byte bounds are invalid")
    bytes_seen = 0
    try:
        try:
            _, first_content = read_bounded_response(
                client,
                source["endpoint"],
                max_response_bytes,
                {**base, "page": 1},
            )
        except ResponseTooLarge as exc:
            raise SourceParseError(str(exc)) from exc
        bytes_seen += len(first_content)
        try:
            payload = json.loads(first_content)
        except json.JSONDecodeError as exc:
            raise SourceParseError("Federal Register response was not valid JSON") from exc
        if (
            not isinstance(payload, dict)
            or not isinstance(payload.get("results"), list)
            or not isinstance(payload.get("total_pages"), int)
        ):
            raise SourceParseError("Federal Register response schema invalid")
        pages = payload["total_pages"]
        if pages < 1 or pages > query["max_pages"]:
            raise SourceParseError(
                f"Bounded query requires {pages} pages; configured maximum is {query['max_pages']}"
            )
        for page in range(1, pages + 1):
            page_data = payload if page == 1 else None
            if page_data is None:
                try:
                    _, content = read_bounded_response(
                        client,
                        source["endpoint"],
                        max_response_bytes,
                        {**base, "page": page},
                    )
                except ResponseTooLarge as exc:
                    raise SourceParseError(str(exc)) from exc
                bytes_seen += len(content)
                if bytes_seen > max_run_bytes:
                    raise SourceParseError("Federal Register response bytes exceed the run bound")
                try:
                    page_data = json.loads(content)
                except json.JSONDecodeError as exc:
                    raise SourceParseError("Federal Register response was not valid JSON") from exc
            if not isinstance(page_data, dict):
                raise SourceParseError(f"Federal Register page {page} schema invalid")
            results = page_data.get("results")
            if not isinstance(results, list) or not results:
                raise SourceParseError(f"Unexpected empty or malformed page {page}")
            for row in results:
                required = ("document_number", "title", "publication_date", "html_url")
                if not isinstance(row, dict) or any(not row.get(key) for key in required):
                    raise SourceParseError("Federal Register record missing required fields")
                date.fromisoformat(row["publication_date"])
                records.append(
                    {
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
                )
        if len(records) < payload.get("count", len(records)):
            raise SourceParseError("Federal Register pagination was incomplete")
        return records
    finally:
        if own_client:
            client.close()
