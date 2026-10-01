"""Paginated read of El Paso's public NewCommercial ArcGIS feature layer."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, date, datetime, timedelta
from typing import Any
from urllib.parse import urlencode, urlsplit

import httpx

from gridlens.ingestion.adapters.bounded_http import read_bounded_response
from gridlens.ingestion.adapters.federal_register import SourceParseError

LAYER = "https://gis.elpasotexas.gov/arcgis/rest/services/Planning/NewCommercial/FeatureServer/0"
HOST = "gis.elpasotexas.gov"
PAGE_SIZE = 1000
MAX_ROWS = 20_000
MAX_RESPONSE_BYTES = 5_000_000
FIELDS = (
    "OBJECTID",
    "Status",
    "Record_Typ",
    "B1_SPECIAL",
    "B1_ALT_ID",
    "B1_APPL_ST",
    "OWNNAME",
    "ISSUEDATE",
    "JOBVALUE",
    "SITEADDR_S",
    "Address",
    "Descriptio",
)


def _request_json(
    client: httpx.Client, url: str, params: dict[str, str | int], maximum: int = MAX_RESPONSE_BYTES
) -> dict[str, Any]:
    headers, body = read_bounded_response(client, url, maximum, params)
    if "json" not in headers.get("content-type", "").lower():
        raise SourceParseError("El Paso ArcGIS endpoint returned non-JSON content")
    try:
        result = json.loads(body)
    except (ValueError, UnicodeDecodeError) as exc:
        raise SourceParseError("El Paso ArcGIS endpoint returned malformed JSON") from exc
    if not isinstance(result, dict) or "error" in result:
        raise SourceParseError("El Paso ArcGIS request failed")
    return result


def _text(value: Any) -> str:
    if value is None:
        return ""
    return " ".join(str(value).split()).strip()


def _row(attributes: dict[str, Any], today: date) -> dict[str, Any]:
    object_id = attributes.get("OBJECTID")
    permit_id = _text(attributes.get("B1_ALT_ID"))
    if isinstance(object_id, bool) or not isinstance(object_id, int) or not permit_id:
        raise SourceParseError("El Paso permit row has no stable GIS and permit identifiers")
    raw_issue = attributes.get("ISSUEDATE")
    event_date = None
    if raw_issue not in (None, ""):
        if isinstance(raw_issue, bool) or not isinstance(raw_issue, int | float):
            raise SourceParseError("El Paso ISSUEDATE is not an ArcGIS epoch timestamp")
        try:
            event_date = datetime.fromtimestamp(raw_issue / 1000, UTC).date()
        except (OverflowError, OSError, ValueError) as exc:
            raise SourceParseError("El Paso ISSUEDATE is outside the supported calendar") from exc
        if event_date > today:
            raise SourceParseError("El Paso permit has a future issue date")
    application_status = _text(attributes.get("B1_APPL_ST")) or "Unknown"
    geocode_status = _text(attributes.get("Status")) or "Unknown"
    address = _text(attributes.get("SITEADDR_S")) or _text(attributes.get("Address"))
    description = _text(attributes.get("Descriptio"))
    work = _text(attributes.get("Record_Typ"))
    project_name = _text(attributes.get("B1_SPECIAL"))
    owner = _text(attributes.get("OWNNAME"))
    identifier = permit_id
    fields = {
        "row": identifier,
        "object_id": str(object_id),
        "project": permit_id,
        "date": event_date.isoformat() if event_date else "Unknown",
        "application_status": application_status,
        "geocode_status": geocode_status,
        "type": work or "Unknown",
        "work": project_name,
        "description": description,
        "address": address,
        "owner": owner,
        "cost": _text(attributes.get("JOBVALUE")),
    }
    abstract = "\n".join(
        f"{key}: {value}"
        for key, value in (
            ("row", identifier),
            ("object_id", str(object_id)),
            ("project", permit_id),
            ("event", "Issued" if event_date else "Unknown"),
            ("date", fields["date"]),
            ("status", application_status),
            ("geocode_status", geocode_status),
            ("type", fields["type"]),
            ("work", project_name),
            ("description", description),
            ("address", address),
            ("owner_name", owner),
            ("cost", fields["cost"]),
        )
        if value
    )
    url = f"{LAYER}/query?" + urlencode(
        {
            "where": f"B1_ALT_ID = '{permit_id.replace(chr(39), chr(39) * 2)}'",
            "outFields": ",".join(FIELDS),
            "returnGeometry": "false",
            "f": "pjson",
        }
    )
    stable_attributes = {key: value for key, value in attributes.items() if key != "OBJECTID"}
    digest = hashlib.sha256(
        json.dumps(stable_attributes, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return {
        "document_number": identifier,
        "title": f"El Paso new commercial permit {permit_id}"
        + (f" — {project_name}" if project_name else ""),
        "abstract": abstract,
        "publication_date": None,
        "event_date": event_date.isoformat() if event_date else None,
        "event_date_label": "ISSUEDATE (official layer field)",
        "html_url": url,
        "extraction_location": f"NewCommercial FeatureServer/0; OBJECTID {object_id}",
        "source_hash": digest,
        "permit": {
            "source_type": "el-paso-new-commercial-permits",
            "city": "El Paso",
            "state": "TX",
            "address": address,
            "description": " ".join(item for item in (project_name, work, description) if item),
            "type": work or "Unknown",
            "status": application_status,
            "application_status": application_status,
            "issuance_event": "issued" if event_date else "Unknown",
            "geocode_status": geocode_status,
            "class": "NewCommercial",
            "cost": fields["cost"],
            "project": permit_id,
            "row_id": identifier,
            "object_id": object_id,
            "application_received": "",
            "owner_name": owner,
            "source_fields": {
                "row": "B1_ALT_ID (stable permit identity)",
                "object_id": "OBJECTID (GIS row identity; may change on republication)",
                "date": "ISSUEDATE",
                "status": "B1_APPL_ST",
                "geocode_status": "Status (not permit lifecycle)",
            },
        },
    }


def retrieve(source: dict[str, Any], client: httpx.Client | None = None) -> list[dict[str, Any]]:
    if source.get("id") != "el-paso-new-commercial-permits" or source.get("endpoint") != LAYER:
        raise SourceParseError("El Paso source is outside its reviewed NewCommercial layer")
    parsed = urlsplit(str(source.get("endpoint")))
    if parsed.scheme != "https" or parsed.hostname != HOST or parsed.query or parsed.fragment:
        raise SourceParseError("El Paso layer URL is outside the official HTTPS endpoint")
    http = client or httpx.Client(
        timeout=25,
        follow_redirects=False,
        headers={"User-Agent": "GridLens public source reader/1.0"},
    )
    today = datetime.now(UTC).date()
    try:
        metadata = _request_json(http, LAYER, {"f": "json"}, maximum=100_000)
        fields = {item.get("name") for item in metadata.get("fields", []) if isinstance(item, dict)}
        pagination = metadata.get("advancedQueryCapabilities", {}).get("supportsPagination")
        maximum = metadata.get("maxRecordCount")
        if (
            not {"OBJECTID", "B1_ALT_ID", "B1_APPL_ST", "ISSUEDATE", "Address"}.issubset(fields)
            or metadata.get("name") != "NewCommercial"
            or pagination is not True
            or not isinstance(maximum, int)
            or not 1 <= maximum <= PAGE_SIZE
        ):
            raise SourceParseError("El Paso NewCommercial schema or pagination contract changed")
        full_count = _request_json(
            http,
            f"{LAYER}/query",
            {"where": "1=1", "returnCountOnly": "true", "f": "json"},
            100_000,
        ).get("count")
        if (
            isinstance(full_count, bool)
            or not isinstance(full_count, int)
            or not 0 < full_count <= MAX_ROWS
        ):
            raise SourceParseError("El Paso layer count is missing or outside the approved bound")
        cutoff = today - timedelta(days=90)
        where = (
            f"ISSUEDATE >= DATE '{cutoff.isoformat()}' "
            f"AND ISSUEDATE < DATE '{(today + timedelta(days=1)).isoformat()}'"
        )
        count = _request_json(
            http,
            f"{LAYER}/query",
            {"where": where, "returnCountOnly": "true", "f": "json"},
            100_000,
        ).get("count")
        if isinstance(count, bool) or not isinstance(count, int) or not 0 < count <= MAX_ROWS:
            raise SourceParseError("El Paso 90-day issue-date count is missing or outside bounds")
        records: list[dict[str, Any]] = []
        records_by_permit: dict[str, dict[str, Any]] = {}
        fetched_features = 0
        prior_object_id = -1
        for offset in range(0, count, maximum):
            page = _request_json(
                http,
                f"{LAYER}/query",
                {
                    "where": where,
                    "outFields": ",".join(FIELDS),
                    "returnGeometry": "false",
                    "orderByFields": "OBJECTID ASC",
                    "resultOffset": offset,
                    "resultRecordCount": maximum,
                    "f": "json",
                },
            )
            features = page.get("features")
            if not isinstance(features, list) or len(features) != min(maximum, count - offset):
                raise SourceParseError("El Paso pagination returned an incomplete page")
            for feature in features:
                attributes = feature.get("attributes") if isinstance(feature, dict) else None
                if not isinstance(attributes, dict):
                    raise SourceParseError("El Paso feature has malformed attributes")
                object_id = attributes.get("OBJECTID")
                if (
                    isinstance(object_id, bool)
                    or not isinstance(object_id, int)
                    or object_id <= prior_object_id
                ):
                    raise SourceParseError(
                        "El Paso pages are unordered or contain duplicate GIS IDs"
                    )
                prior_object_id = object_id
                fetched_features += 1
                record = _row(attributes, today)
                permit_id = record["document_number"]
                prior = records_by_permit.get(permit_id)
                if prior is not None:
                    if prior["source_hash"] != record["source_hash"]:
                        raise SourceParseError(
                            "El Paso repeats a permit ID with conflicting row facts"
                        )
                    continue
                records_by_permit[permit_id] = record
                event = record["event_date"]
                if event is None or date.fromisoformat(event) < cutoff:
                    raise SourceParseError(
                        "El Paso issue-date filter returned an out-of-window row"
                    )
        final_count = _request_json(
            http,
            f"{LAYER}/query",
            {"where": where, "returnCountOnly": "true", "f": "json"},
            100_000,
        ).get("count")
        if final_count != count or fetched_features != count:
            raise SourceParseError("El Paso layer changed during paginated retrieval")
        records = list(records_by_permit.values())
        dated = [date.fromisoformat(item["event_date"]) for item in records if item["event_date"]]
        if not dated:
            raise SourceParseError(
                "El Paso NewCommercial issue-date data is missing or over 30 days old"
            )
        latest_query = _request_json(
            http,
            f"{LAYER}/query",
            {
                "where": where,
                "outFields": "OBJECTID,ISSUEDATE",
                "returnGeometry": "false",
                "orderByFields": "ISSUEDATE DESC,OBJECTID DESC",
                "resultRecordCount": 1,
                "f": "json",
            },
            100_000,
        ).get("features")
        if not isinstance(latest_query, list) or len(latest_query) != 1:
            raise SourceParseError("El Paso could not verify the newest in-window issue date")
        latest_attributes = latest_query[0].get("attributes", {})
        latest_timestamp = latest_attributes.get("ISSUEDATE")
        if not isinstance(latest_timestamp, int | float) or isinstance(latest_timestamp, bool):
            raise SourceParseError("El Paso newest issue-date verification is malformed")
        latest_date = datetime.fromtimestamp(latest_timestamp / 1000, UTC).date()
        if latest_date > today or (today - latest_date).days > 60:
            raise SourceParseError(
                "El Paso NewCommercial issue-date data is missing or over 60 days old"
            )
        for record in records:
            record["permit"]["layer_feature_count"] = full_count
            record["permit"]["window_feature_count"] = count
            record["permit"]["window_unique_permit_count"] = len(records)
            record["permit"]["source_as_of"] = today.isoformat()
        return records
    finally:
        if client is None:
            http.close()
