import json
from datetime import time
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

REGISTRY_PATH = Path(__file__).resolve().parents[4] / "config" / "sources" / "registry.v1.json"


def load_registry(path: Path = REGISTRY_PATH) -> list[dict[str, Any]]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if raw.get("version") != 1 or not isinstance(raw.get("sources"), list):
        raise ValueError("Unsupported source registry version")
    ids: set[str] = set()
    for source in raw["sources"]:
        if not all(
            source.get(k)
            for k in ("id", "publisher", "endpoint", "family", "geography", "retrieval_method")
        ):
            raise ValueError("Source definition lacks required fields")
        cadence = source.get("cadence_hours", 24)
        if type(cadence) is not int or cadence <= 0:
            raise ValueError("Source cadence must be a positive number of hours")
        default_mode = "utc_hourly" if cadence < 24 else "local_daily"
        schedule_mode = source.get("schedule_mode", default_mode)
        if schedule_mode not in {"utc_hourly", "local_daily"}:
            raise ValueError("Unsupported source schedule mode")
        if schedule_mode == "utc_hourly" and cadence >= 24:
            raise ValueError("UTC hourly schedules require a cadence below 24 hours")
        if schedule_mode == "local_daily" and cadence % 24 != 0:
            raise ValueError("Local daily schedules require a cadence in whole 24-hour days")
        try:
            ZoneInfo(source.get("timezone", "America/Chicago"))
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError("Source timezone must be a valid IANA zone") from exc
        try:
            time.fromisoformat(source.get("schedule_anchor_time", "07:00:00"))
        except ValueError as exc:
            raise ValueError("Source schedule anchor must be a local clock time") from exc
        allowed_hosts = {
            "json-api": {"www.federalregister.gov"},
            "federal-register-json": {"www.federalregister.gov"},
            "nc-commerce-html": {"www.commerce.nc.gov"},
            "publisher-rss": {
                "www.datacenterdynamics.com",
                "www.utilitydive.com",
                "www.manufacturingdive.com",
                "www.constructiondive.com",
                "www.ogj.com",
                "mjbizdaily.com",
            },
            "socrata-permits": {
                "data.austintexas.gov",
                "data.seattle.gov",
                "data.cityofchicago.org",
            },
            "boston-ckan-permits": {"data.boston.gov"},
            "rrc-drilling-permits": {"mft.rrc.texas.gov"},
            "rrc-flare-exceptions": {"webapps.rrc.state.tx.us"},
            "houston-weekly-permits": {"www.houstonpermittingcenter.org"},
            "dallas-monthly-permits": {"dallascityhall.com"},
            "el-paso-new-commercial-permits": {"gis.elpasotexas.gov"},
            "georgia-air-permits": {"epd.georgia.gov"},
            "ma-cultivation-applications": {"masscannabiscontrol.com"},
            "taylor-newsflash": {"taylortx.gov"},
            "tceq-nsr-pending": {"www.tceq.texas.gov"},
            "tceq-temporary-batch-plants": {"www.tceq.texas.gov"},
            "ceqanet-data-centers": {"ceqanet.lci.ca.gov"},
            "fort-worth-permits": {"services5.arcgis.com"},
            "san-antonio-permits": {"data.sanantonio.gov"},
        }
        # Only adapters that return every listed row or fail may declare a complete snapshot;
        # absence from such a snapshot is then a reviewable status change.
        if source.get("snapshot_complete") and source["retrieval_method"] not in {
            "georgia-air-permits",
            "tceq-nsr-pending",
            "tceq-temporary-batch-plants",
        }:
            raise ValueError("Source cannot declare a complete snapshot")
        if source["id"] in ids or urlparse(source["endpoint"]).hostname not in allowed_hosts.get(
            source["retrieval_method"], set()
        ):
            raise ValueError("Duplicate source ID or unapproved host")
        ids.add(source["id"])
        query = source.get("query", {})
        valid_window = source["retrieval_method"] in {
            "rrc-drilling-permits",
            "rrc-flare-exceptions",
            "houston-weekly-permits",
            "dallas-monthly-permits",
            "el-paso-new-commercial-permits",
            "publisher-rss",
            "georgia-air-permits",
            "taylor-newsflash",
            "ma-cultivation-applications",
            "tceq-nsr-pending",
            "tceq-temporary-batch-plants",
        } or (1 <= query.get("window_days", 0) <= 90)
        if source["retrieval_method"] in {"json-api", "federal-register-json"}:
            bounded = (
                1 <= query.get("max_pages", 0) <= 10
                and query.get("per_page") == 100
                and 1024 <= query.get("max_response_bytes", 0) <= 5_000_000
                and query.get("max_response_bytes", 0) <= query.get("max_run_bytes", 0)
                and query.get("max_run_bytes", 0) <= 100_000_000
            )
        elif source["retrieval_method"] == "nc-commerce-html":
            bounded = (
                1 <= query.get("max_pages", 0) <= 20
                and "per_page" not in query
                and 1 <= query.get("max_articles", 0) <= 300
                and 1024 <= query.get("max_response_bytes", 0) <= 5_000_000
                and query.get("max_response_bytes", 0)
                <= query.get("max_run_bytes", 0)
                <= 100_000_000
            )
        elif source["retrieval_method"] == "publisher-rss":
            bounded = (
                source.get("cadence_hours") == 1
                and 1024 <= query.get("max_response_bytes", 0) <= 5_000_000
                and 1 <= query.get("max_items", 0) <= 50
            )
        elif source["retrieval_method"] == "socrata-permits":
            bounded = (
                source.get("family") == "construction-permits"
                and source.get("cadence_hours") == 24
                and query.get("per_page") == 1000
                and 1 <= query.get("window_days", 0) <= 90
                and 1 <= query.get("max_pages", 0) <= 20
                and query.get("max_response_bytes") == 2_000_000
                and query.get("max_run_bytes") == 20_000_000
                and source.get("city") in {"Austin", "Seattle", "Chicago"}
                and source.get("state") in {"TX", "WA", "IL"}
            )
        elif source["retrieval_method"] == "rrc-drilling-permits":
            bounded = (
                source.get("cadence_hours") == 24
                and source.get("family") == "construction-permits"
                and query.get("max_snapshot_bytes") == 10_000_000
                and query.get("max_roots_per_snapshot") == 5000
                and query.get("previous_month_overlap") is True
            )
        elif source["retrieval_method"] == "rrc-flare-exceptions":
            bounded = (
                source.get("id") == "texas-rrc-flare-vent-exceptions"
                and source.get("family") == "oil-gas-regulatory-applications"
                and source.get("geography") == "Texas"
                and source.get("cadence_hours") == 24
                and query.get("window_days") == 3
                and query.get("rows_per_page") == 10
                and query.get("max_pages") == 50
                and query.get("max_records") == 500
                and query.get("max_response_bytes") == 2_000_000
                and query.get("max_run_bytes") == 20_000_000
                and urlparse(source["endpoint"]).scheme == "https"
                and urlparse(source["endpoint"]).hostname == "webapps.rrc.state.tx.us"
                and urlparse(source["endpoint"]).path == "/swr32/publicquery.xhtml"
                and not urlparse(source["endpoint"]).query
            )
        elif source["retrieval_method"] == "houston-weekly-permits":
            bounded = source.get("cadence_hours") == 24 and query.get("max_reports") == 4
        elif source["retrieval_method"] == "dallas-monthly-permits":
            bounded = (
                source.get("family") == "construction-permits"
                and source.get("cadence_hours") == 24
                and query.get("max_reports") == 4
                and source.get("city") == "Dallas"
                and source.get("state") == "TX"
            )
        elif source["retrieval_method"] == "el-paso-new-commercial-permits":
            bounded = (
                source.get("family") == "construction-permits"
                and source.get("cadence_hours") == 24
                and query.get("window_days") == 90
                and query.get("max_records") == 20000
                and query.get("page_size") == 1000
                and source.get("city") == "El Paso"
                and source.get("state") == "TX"
            )
        elif source["retrieval_method"] == "georgia-air-permits":
            bounded = (
                source.get("family") == "construction-permits"
                and source.get("cadence_hours") == 24
                and query.get("rows_per_page") == 100
                and 1 <= query.get("max_pages", 0) <= 5
                and 1 <= query.get("max_records", 0) <= 500
                and query.get("max_response_bytes") == 2_000_000
                and query.get("max_run_bytes") == 30_000_000
                and 1 <= query.get("max_pdfs_per_run", 0) <= 50
                and query.get("max_pdf_bytes") == 4_000_000
                and query.get("max_pdf_pages") == 200
                and query.get("max_pdf_total_pages") == 5000
                and source.get("geography") == "Georgia"
            )
        elif source["retrieval_method"] == "boston-ckan-permits":
            bounded = (
                source.get("id") == "boston-building-permits"
                and source.get("family") == "construction-permits"
                and source.get("cadence_hours") == 24
                and source.get("geography") == "Boston, Massachusetts"
                and source.get("city") == "Boston"
                and source.get("state") == "MA"
                and query.get("window_days") == 90
                and query.get("page_size") == 1000
                and query.get("max_pages") == 20
                and query.get("max_records") == 20000
                and query.get("max_response_bytes") == 2_000_000
                and query.get("max_run_bytes") == 20_000_000
                and urlparse(source["endpoint"]).scheme == "https"
                and urlparse(source["endpoint"]).hostname == "data.boston.gov"
                and urlparse(source["endpoint"]).path == "/api/3/action/datastore_search_sql"
                and not urlparse(source["endpoint"]).query
            )
        elif source["retrieval_method"] == "ma-cultivation-applications":
            bounded = (
                source.get("id") == "ma-ccc-cultivation-applications"
                and source.get("family") == "cultivation-license-applications"
                and source.get("cadence_hours") == 24
                and query.get("max_snapshot_bytes") == 10_000_000
                and query.get("max_records") == 2500
                and query.get("max_snapshot_age_days") == 30
                and query.get("max_application_event_age_days") == 120
                and source.get("geography") == "Massachusetts"
                and urlparse(source["endpoint"]).scheme == "https"
                and urlparse(source["endpoint"]).hostname == "masscannabiscontrol.com"
                and urlparse(source["endpoint"]).path == "/resource/l_applications_all_details.json"
                and not urlparse(source["endpoint"]).query
            )
        elif source["retrieval_method"] == "tceq-temporary-batch-plants":
            bounded = (
                source.get("cadence_hours") == 24
                and source.get("geography") == "Texas"
                and 0 <= query.get("max_notices", -1) <= 40
                and set(query) == {"max_notices"}
            )
        elif source["retrieval_method"] == "san-antonio-permits":
            bounded = (
                source.get("cadence_hours") == 24
                and source.get("family") == "construction-permits"
                and source.get("geography") == "San Antonio, Texas"
                and set(query) == {"window_days"}
                and 1 <= query.get("window_days", 0) <= 90
            )
        elif source["retrieval_method"] == "fort-worth-permits":
            bounded = (
                source.get("cadence_hours") == 24
                and source.get("family") == "construction-permits"
                and source.get("geography") == "Fort Worth, Texas"
                and set(query) == {"window_days"}
                and 1 <= query.get("window_days", 0) <= 90
            )
        elif source["retrieval_method"] == "ceqanet-data-centers":
            bounded = (
                source.get("cadence_hours") == 24
                and source.get("family") == "environmental-review-filings"
                and source.get("geography") == "California"
                and set(query) == {"development_types", "window_days", "max_documents"}
                and 1 <= query.get("max_documents", 0) <= 60
                and isinstance(query.get("development_types"), list)
                and 1 <= len(query["development_types"]) <= 5
            )
        elif source["retrieval_method"] == "tceq-nsr-pending":
            bounded = (
                source.get("cadence_hours") == 24
                and source.get("geography") == "Texas"
                and 0 <= query.get("max_summaries", -1) <= 60
                and set(query) == {"max_summaries"}
            )
        elif source["retrieval_method"] == "taylor-newsflash":
            bounded = (
                source.get("family") == "municipal-planning-news"
                and source.get("cadence_hours") == 24
                and 1 <= query.get("archive_window_days", 0) <= 90
                and 0 <= query.get("archive_overlap_days", -1) <= 14
                and query.get("archive_window_days", 0) + query.get("archive_overlap_days", 0) <= 90
                and query.get("archive_count") in {10, 25, 50}
                and 1 <= query.get("max_pages", 0) <= 20
                and 1024 <= query.get("max_response_bytes", 0) <= 5_000_000
                and query.get("max_response_bytes", 0)
                <= query.get("max_run_bytes", 0)
                <= 100_000_000
                and source.get("geography") == "Taylor, Texas"
            )
        else:
            bounded = False
        if not valid_window or not bounded:
            raise ValueError("Source query exceeds its bounded collection window")
    return raw["sources"]
