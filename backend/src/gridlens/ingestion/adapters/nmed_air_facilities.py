"""NMED air-quality facility layers (ArcGIS MapServer): a bounded facility identity universe.

Verified live 2026-11-04 (read-only; see docs/engineering/widen-document-sources-20261103.md):
``https://mercator.env.nm.gov/server/rest/services/aqb/air_facilities/MapServer`` exposes seven
layers (0 Major-Title V, 1 Minor, 2 Synthetic Minor, 3 No Permit Required, 4 Notice of Exemption,
5 Notice of Intent, 6 Nonactive), all with the same twelve fields, ``maxRecordCount`` 2000,
standard ``resultOffset`` paging. **The layers carry no AI number and no permit number**, only
name, address, county, status, type, class and latitude/longitude, so these records are facility
identity and coordinates for later joins, never an equipment or demand source. The layer class
is the permit class of the facility, not a permit identifier.

This module reads the layers; it does not write anywhere. It is pure with respect to the
database. Bounds: exact host and path, fixed query shape, at most one request per second, a
response byte cap, a per-run record and request cap, redirects never followed, the first 429 or
503 ends the run with ``Retry-After`` reported, no exception text or response content kept. A
layer that stops at a cap while the server still reports more rows is marked ``truncated``: a
partial universe is never presented as complete.
"""

from __future__ import annotations

import hashlib
import json
import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlencode

import httpx

from gridlens.ingestion.adapters import nmed_http
from gridlens.ingestion.adapters import tceq_application_documents as shared
from gridlens.ingestion.adapters.tceq_application_documents import DocumentFailure, Pacer

VERSION = "nmed-air-facilities-v1"
SOURCE_KEY = "nmed-air-facilities"
HOST = nmed_http.ARCGIS_HOST
SERVICE_PATH = "/server/rest/services/aqb/air_facilities/MapServer"
LAYER_NAMES: dict[int, str] = {
    0: "Major-Title V",
    1: "Minor",
    2: "Synthetic Minor",
    3: "No Permit Required",
    4: "Notice of Exemption",
    5: "Notice of Intent",
    6: "Nonactive",
}
FIELDS = (
    "OBJECTID",
    "AI_NAME",
    "PHYSICAL_ADDRESS_LINE_1",
    "MUNICIPALITY",
    "COUNTY",
    "STATE",
    "ZIP",
    "AI_STATUS",
    "AI_TYPE",
    "FACILITY_CLASS",
    "LAT",
    "LON",
)
_WHERE = {False: "1=1", True: "AI_TYPE LIKE 'O&G%'"}
MAX_PAGE_SIZE = 1000
MAX_RECORDS = 10_000
MAX_REQUESTS = 30
MAX_RESPONSE_BYTES = 5_000_000
# Generous New Mexico bounding box; a coordinate outside it is unknown, never moved.
LAT_RANGE = (31.0, 37.1)
LON_RANGE = (-109.2, -102.9)
_TEXT_LIMITS = {
    "AI_NAME": 100,
    "PHYSICAL_ADDRESS_LINE_1": 100,
    "MUNICIPALITY": 31,
    "COUNTY": 31,
    "STATE": 2,
    "ZIP": 9,
    "AI_STATUS": 31,
    "AI_TYPE": 63,
    "FACILITY_CLASS": 31,
}
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")
_DEADLINE_MARGIN_SECONDS = 30.0


@dataclass(frozen=True, slots=True)
class FacilityConfig:
    layers: tuple[int, ...] = (0, 1, 2)
    page_size: int = 500
    max_records: int = 3000
    max_requests: int = 12
    oil_gas_only: bool = True


def valid_config(raw: Any) -> bool:
    if not isinstance(raw, dict) or set(raw) != {
        "layers",
        "page_size",
        "max_records",
        "max_requests",
        "oil_gas_only",
    }:
        return False
    layers = raw["layers"]
    return (
        isinstance(layers, list)
        and 1 <= len(layers) <= len(LAYER_NAMES)
        and all(type(item) is int and item in LAYER_NAMES for item in layers)
        and len(set(layers)) == len(layers)
        and type(raw["page_size"]) is int
        and 50 <= raw["page_size"] <= MAX_PAGE_SIZE
        and type(raw["max_records"]) is int
        and 1 <= raw["max_records"] <= MAX_RECORDS
        and type(raw["max_requests"]) is int
        and 1 <= raw["max_requests"] <= MAX_REQUESTS
        and type(raw["oil_gas_only"]) is bool
    )


def config_from_dict(raw: dict[str, Any]) -> FacilityConfig:
    if not valid_config(raw):
        raise ValueError("NMED air-facilities configuration is invalid")
    return FacilityConfig(
        layers=tuple(raw["layers"]),
        page_size=raw["page_size"],
        max_records=raw["max_records"],
        max_requests=raw["max_requests"],
        oil_gas_only=raw["oil_gas_only"],
    )


def layer_query_url(layer: int, offset: int, count: int, *, oil_gas_only: bool) -> str:
    """The one query shape this module sends. Nothing else is ever requested."""
    if layer not in LAYER_NAMES or offset < 0 or not 1 <= count <= MAX_PAGE_SIZE:
        raise ValueError("NMED layer query is outside the reviewed shape")
    query = urlencode(
        {
            "where": _WHERE[oil_gas_only],
            "outFields": ",".join(FIELDS),
            "orderByFields": "OBJECTID",
            "resultOffset": offset,
            "resultRecordCount": count,
            "returnGeometry": "false",
            "f": "json",
        }
    )
    return f"https://{HOST}{SERVICE_PATH}/{layer}/query?{query}"


@dataclass(slots=True)
class FacilityResult:
    records: list[dict[str, Any]] = field(default_factory=list)
    layers: dict[int, dict[str, Any]] = field(default_factory=dict)
    failures: list[str] = field(default_factory=list)  # codes only
    requests: int = 0
    retry_after_seconds: int | None = None
    rate_limited: bool = False


def _clean(value: Any, limit: int) -> str | None:
    if not isinstance(value, str):
        return None
    text = " ".join(_CONTROL.sub(" ", value).split())[:limit]
    return text or None


def _coordinate(value: Any, bounds: tuple[float, float]) -> float | None:
    if type(value) not in (int, float) or isinstance(value, bool):
        return None
    number = float(value)
    return round(number, 6) if bounds[0] <= number <= bounds[1] else None


def normalize_feature(layer: int, feature: Any) -> dict[str, Any] | None:
    """One layer feature as a facility identity record, or None when it is unusable."""
    attrs = feature.get("attributes") if isinstance(feature, dict) else None
    if not isinstance(attrs, dict):
        return None
    object_id = attrs.get("OBJECTID")
    name = _clean(attrs.get("AI_NAME"), _TEXT_LIMITS["AI_NAME"])
    if type(object_id) is not int or object_id < 0 or name is None:
        return None
    record: dict[str, Any] = {
        "version": VERSION,
        "source": SOURCE_KEY,
        "layer_id": layer,
        "permit_class": LAYER_NAMES[layer],
        "object_id": object_id,
        # Layer-local only: ArcGIS object ids are not a durable cross-publish identity.
        "identity_key": f"nmed-aq:{layer}:{object_id}",
        "name": name,
        "address": _clean(attrs.get("PHYSICAL_ADDRESS_LINE_1"), 100),
        "municipality": _clean(attrs.get("MUNICIPALITY"), 31),
        "county": _clean(attrs.get("COUNTY"), 31),
        "state": _clean(attrs.get("STATE"), 2),
        "zip": _clean(attrs.get("ZIP"), 9),
        "status": _clean(attrs.get("AI_STATUS"), 31),
        "facility_type": _clean(attrs.get("AI_TYPE"), 63),
        "facility_class": _clean(attrs.get("FACILITY_CLASS"), 31),
        "latitude": _coordinate(attrs.get("LAT"), LAT_RANGE),
        "longitude": _coordinate(attrs.get("LON"), LON_RANGE),
        # The public layers publish neither: unknown, not guessed from the name.
        "ai_number": None,
        "permit_number": None,
        "identity_basis": "name, county and layer; no AI or permit number is published",
    }
    if record["latitude"] is None or record["longitude"] is None:
        record["latitude"] = record["longitude"] = None
    digest = json.dumps(record, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    record["record_hash"] = hashlib.sha256(digest.encode()).hexdigest()
    return record


def _parse_page(body: bytes) -> tuple[list[Any], bool]:
    try:
        payload = json.loads(body)
    except (ValueError, UnicodeDecodeError) as exc:
        raise DocumentFailure("schema_invalid") from exc
    if not isinstance(payload, dict):
        raise DocumentFailure("schema_invalid")
    if "error" in payload:
        raise DocumentFailure("arcgis_error")
    features = payload.get("features")
    exceeded = payload.get("exceededTransferLimit", False)
    if not isinstance(features, list) or not isinstance(exceeded, bool):
        raise DocumentFailure("schema_invalid")
    return features, exceeded


def _fetch_page(
    client: httpx.Client, url: str, pacer: Callable[[], None]
) -> tuple[list[Any], bool]:
    def run() -> tuple[list[Any], bool]:
        with nmed_http.open_pinned(
            client, url, HOST, headers={"Accept": "application/json"}, before_request=pacer
        ) as response:
            nmed_http.check_status(response)
            if shared._media_type(response.headers) != "application/json":
                raise DocumentFailure("wrong_content_type")
            return _parse_page(nmed_http.read_limited(response, MAX_RESPONSE_BYTES))

    page: tuple[list[Any], bool] = shared._guard_network(run)
    return page


def fetch_facilities(
    client: httpx.Client | None,
    config: FacilityConfig,
    *,
    pacer: Callable[[], None] | None = None,
    deadline: float | None = None,
) -> FacilityResult:
    """Read the configured layers page by page. Never raises for a publisher or data fault."""
    result = FacilityResult()
    owns = client is None
    http = client or httpx.Client(timeout=30.0, follow_redirects=False, trust_env=False)
    pace = pacer or Pacer()
    try:
        for layer in config.layers:
            info: dict[str, Any] = {"name": LAYER_NAMES[layer], "rows": 0, "truncated": False}
            result.layers[layer] = info
            offset = 0
            seen: set[int] = set()
            while True:
                if result.requests >= config.max_requests or (
                    len(result.records) >= config.max_records
                ):
                    info["truncated"] = True
                    break
                if deadline is not None and time.monotonic() > deadline - _DEADLINE_MARGIN_SECONDS:
                    info["truncated"] = True
                    result.failures.append("deadline")
                    return result
                count = min(config.page_size, config.max_records - len(result.records))
                url = layer_query_url(layer, offset, count, oil_gas_only=config.oil_gas_only)
                result.requests += 1
                try:
                    features, exceeded = _fetch_page(http, url, pace)
                except DocumentFailure as failure:
                    result.failures.append(failure.code)
                    info["truncated"] = True
                    if failure.rate_limited:
                        result.rate_limited = True
                        result.retry_after_seconds = failure.retry_after
                        return result
                    break
                for feature in features:
                    record = normalize_feature(layer, feature)
                    if record is None or record["object_id"] in seen:
                        info["skipped"] = info.get("skipped", 0) + 1
                        continue
                    seen.add(record["object_id"])
                    result.records.append(record)
                    info["rows"] += 1
                offset += len(features)
                # A full page is followed by one more request even when the server omits
                # exceededTransferLimit, so a complete layer is only claimed on a short page.
                if not features or (not exceeded and len(features) < count):
                    break
        return result
    finally:
        if owns:
            http.close()
