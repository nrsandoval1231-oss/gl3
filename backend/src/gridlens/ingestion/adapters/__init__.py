from typing import Any

import httpx

from gridlens.ingestion.adapters.federal_register import SourceParseError
from gridlens.ingestion.adapters.nc_commerce import retrieve as retrieve_nc_commerce
from gridlens.ingestion.adapters.publisher_rss import retrieve as retrieve_publisher_rss


def retrieve_source(
    source: dict[str, Any], client: httpx.Client | None = None
) -> list[dict[str, Any]]:
    method = source.get("retrieval_method")
    if method in {"federal-register-json", "json-api"}:
        from gridlens.ingestion.adapters.federal_register import retrieve

        return retrieve(source, client)
    if method == "nc-commerce-html":
        return retrieve_nc_commerce(source, client)
    if method == "publisher-rss":
        return retrieve_publisher_rss(source, client)
    raise SourceParseError(f"Unsupported source retrieval method: {method}")
