from typing import Any

import httpx

from gridlens.ingestion.adapters.dallas_permits import retrieve as retrieve_dallas_permits
from gridlens.ingestion.adapters.el_paso_permits import retrieve as retrieve_el_paso_permits
from gridlens.ingestion.adapters.federal_register import SourceParseError
from gridlens.ingestion.adapters.georgia_air_permits import retrieve as retrieve_georgia_air_permits
from gridlens.ingestion.adapters.houston_permits import retrieve as retrieve_houston_permits
from gridlens.ingestion.adapters.ma_cultivation import retrieve as retrieve_ma_cultivation
from gridlens.ingestion.adapters.nc_commerce import retrieve as retrieve_nc_commerce
from gridlens.ingestion.adapters.publisher_rss import retrieve as retrieve_publisher_rss
from gridlens.ingestion.adapters.socrata_permits import retrieve as retrieve_socrata_permits
from gridlens.ingestion.adapters.taylor_newsflash import retrieve as retrieve_taylor_newsflash


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
    if method == "rrc-drilling-permits":
        from gridlens.ingestion.adapters.rrc_drilling import retrieve

        return retrieve(source, client)
    if method == "houston-weekly-permits":
        return retrieve_houston_permits(source, client)
    if method == "dallas-monthly-permits":
        return retrieve_dallas_permits(source, client)
    if method == "el-paso-new-commercial-permits":
        return retrieve_el_paso_permits(source, client)
    if method == "socrata-permits":
        return retrieve_socrata_permits(source, client)
    if method == "georgia-air-permits":
        return retrieve_georgia_air_permits(source, client)
    if method == "ma-cultivation-applications":
        return retrieve_ma_cultivation(source, client)
    if method == "taylor-newsflash":
        return retrieve_taylor_newsflash(source, client)
    raise SourceParseError(f"Unsupported source retrieval method: {method}")
