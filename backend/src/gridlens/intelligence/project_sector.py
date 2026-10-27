"""Small, evidence-bounded project metadata for project-first browse results."""

from __future__ import annotations

import re
from typing import Any

from gridlens.intelligence.rrc_counties import county_label

_RRC = "texas-rrc-drilling-permits"
_EMPTY = {"", "unknown", "n/a", "na", "none", "null", "unavailable"}


def _clean(value: Any) -> str | None:
    if not isinstance(value, str | int):
        return None
    result = " ".join(str(value).split())
    return result if result.casefold() not in _EMPTY else None


def _first(source: dict[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = _clean(source.get(key))
        if value:
            return value
    return None


def result_metadata(compact: dict[str, Any]) -> dict[str, Any]:
    """Return displayable metadata supported by retained compact evidence.

    This function deliberately does not infer lifecycle progress from project
    names or opaque source payloads. Callers can safely omit null fields.
    """
    if not isinstance(compact, dict):
        compact = {}
    evidence = compact.get("evidence")
    evidence = evidence if isinstance(evidence, list) else []
    rrc_records = compact.get("_browse_rrc_records")
    rrc_records = (
        [row for row in rrc_records if isinstance(row, dict)]
        if isinstance(rrc_records, list)
        else []
    )
    tdlr_records = compact.get("_browse_tdlr_records")
    tdlr_records = (
        [row for row in tdlr_records if isinstance(row, dict)]
        if isinstance(tdlr_records, list)
        else []
    )
    official_records = compact.get("_browse_rrc_official")
    official_records = (
        [official_records]
        if isinstance(official_records, dict)
        else [row for row in official_records if isinstance(row, dict)]
        if isinstance(official_records, list)
        else []
    )
    relationship_records = compact.get("_browse_oil_gas_relationship")
    relationship_records = (
        [row for row in relationship_records if isinstance(row, dict)]
        if isinstance(relationship_records, list)
        else []
    )
    title = _first(compact, "browse_title", "title")
    name = _first(compact, "name", "project_name", "asset_name")
    asset = _first(compact, "asset_type", "asset_kind") or ""
    text = " ".join(
        str(compact.get(k) or "") for k in ("name", "browse_title", "asset_type", "description")
    ).casefold()
    source_ids = {str(row.get("source_id") or "") for row in evidence if isinstance(row, dict)}
    supported_oil_gas_assets = {
        "upstream_well",
        "pipeline_infrastructure",
        "compressor_station",
        "gas_processing_plant",
        "cryogenic_plant",
        "swd_facility",
        "produced_water_infrastructure",
        "gathering_system",
        "pipeline_pump_compressor_facility",
        "field_electrification_project",
    }
    valid_relationships = [
        row
        for row in relationship_records
        if row.get("verified") is True
        and isinstance(row.get("source_id"), str)
        and row.get("source_id")
        and isinstance(row.get("evidence_id"), str | int)
        and isinstance(row.get("matched_context"), list)
        and any(
            isinstance(value, str)
            and re.fullmatch(
                r"(?:oilfield|oil field|oil well|gas well|oil production|gas production|"
                r"upstream oil|upstream gas|natural gas gathering|gas gathering system|"
                r"associated gas|saltwater disposal|produced water|swd facility|"
                r"crude oil pipeline|oil transmission pipeline|natural gas liquids|"
                r"ngl processing|gas processing plant|oilfield electrification|"
                r"oil and gas field electrification)",
                value,
                re.I,
            )
            for value in row["matched_context"]
        )
    ]
    attributed_oil_gas = bool(valid_relationships)
    oil_gas = None
    asset_identity = None
    lifecycle_event = None
    permit_event = None
    valid_official = []
    for row in official_records:
        identity = row.get("asset_identity")
        if (
            row.get("identity_validated") is True
            and row.get("source") in {"texas-rrc-w1-detail", "texas-rrc-completion-packet"}
            and isinstance(identity, dict)
            and identity.get("kind") == "us_well_api"
            and re.fullmatch(r"42\d{8}", str(identity.get("value") or ""))
            and isinstance(row.get("native_content_hash"), str)
            and re.fullmatch(r"[a-f0-9]{64}", row["native_content_hash"])
            and isinstance(row.get("identity"), dict)
            and isinstance(row.get("source_url"), str)
            and row["source_url"].startswith(
                "https://webapps2.rrc.texas.gov/EWA/"
                if row.get("source") == "texas-rrc-w1-detail"
                else "https://webapps.rrc.texas.gov/CMPL/"
            )
        ):
            identity = row["identity"]
            matching_native_rows = [
                candidate
                for candidate in rrc_records
                if _clean(candidate.get("operator_number"))
                == _clean(identity.get("operator_number"))
                and _clean(candidate.get("lease")) == _clean(identity.get("lease"))
                and re.sub(r"\s+", "", str(candidate.get("well") or "")).casefold()
                == re.sub(
                    r"\s+", "", str(identity.get("well") or identity.get("well_number") or "")
                ).casefold()
                and (
                    row.get("source") != "texas-rrc-w1-detail"
                    or not candidate.get("document_number")
                    or str(candidate["document_number"]).zfill(7)
                    == str(identity.get("permit_number") or "").zfill(7)
                )
            ]
            if not rrc_records or matching_native_rows:
                valid_official.append(row)
    has_rrc = (
        bool(rrc_records)
        or _RRC in source_ids
        or compact.get("source_id") == _RRC
        or bool(valid_official)
    )
    official_apis = {row["asset_identity"]["value"] for row in valid_official}
    if len(official_apis) == 1:
        api = next(iter(official_apis))
        identities = [
            row["identity"] for row in valid_official if row["asset_identity"]["value"] == api
        ]
        refs = sorted(
            {
                ref
                for row in valid_official
                for ref in (
                    row["asset_identity"].get("evidence_refs", []) + row.get("evidence_refs", [])
                )
                if isinstance(ref, str) and ref
            }
        )
        asset_identity = {
            "kind": "us_well_api",
            "value": api,
            "source": "Texas Railroad Commission official well record",
            "evidence_refs": refs,
            "identity_validated": True,
        }
        if (
            len(
                {
                    (
                        _clean(row.get("operator_number")),
                        _clean(row.get("lease")),
                        _clean(row.get("well") or row.get("well_number")),
                    )
                    for row in identities
                }
            )
            == 1
        ):
            identity = identities[0]
            name = _clean(identity.get("lease")) or name
            well = _clean(identity.get("well") or identity.get("well_number"))
            operator_name = _clean(identity.get("operator"))
            title = " · ".join(
                part for part in (operator_name, name, f"Well {well}" if well else None) if part
            )
        official_events = [
            event
            for row in valid_official
            for event in row.get("events", [])
            if isinstance(event, dict)
            and event.get("source") in {"texas-rrc-w1-detail", "texas-rrc-completion-packet"}
            and isinstance(event.get("date"), str)
            and re.fullmatch(r"\d{4}-\d{2}-\d{2}", event["date"])
        ]
        if official_events:
            lifecycle_event = max(official_events, key=lambda event: str(event["date"]))
    if has_rrc:
        # RRC permit identity is explicit and source-bound. Permit issue is not spud.
        unique = {
            tuple(_clean(row.get(k)) for k in ("operator", "operator_number", "lease", "well"))
            for row in rrc_records
        }
        row = rrc_records[0] if len(unique) == 1 and rrc_records else {}
        fields: dict[str, Any] = {}
        for key, aliases in {
            "operator": ("operator",),
            "operator_number": ("operator_number",),
            "lease": ("lease",),
            "well_number": ("well", "well_number"),
            "county": ("county",),
            "county_code": ("county_code",),
            "status": ("status",),
        }.items():
            if key == "status" and len({_clean(row.get("status")) for row in rrc_records}) > 1:
                continue
            value = _first(row, *aliases) or _first(compact, *aliases)
            if value:
                fields[key] = value
        if len(official_apis) == 1:
            identities = [
                candidate["identity"]
                for candidate in valid_official
                if candidate["asset_identity"]["value"] in official_apis
            ]
            for out, source_keys in {
                "operator": ("operator",),
                "operator_number": ("operator_number",),
                "lease": ("lease",),
                "well_number": ("well_number", "well"),
                "county": ("county",),
                "county_code": ("county_code",),
            }.items():
                values = {_clean(_first(identity, *source_keys)) for identity in identities}
                if len(values) == 1:
                    value = next(iter(values))
                    if value:
                        fields[out] = value
        issue_values = {
            _clean(candidate.get("permit_issue_date") or candidate.get("date"))
            for candidate in rrc_records
        }
        issue = (
            _first(row, "permit_issue_date") or _first(row, "date")
            if len(issue_values) == 1
            else _first(compact, "permit_issue_date", "issued")
            if not rrc_records
            else None
        )
        if issue and re.fullmatch(r"\d{4}-\d{2}-\d{2}", issue):
            fields["permit_issue_date"] = issue
        amendment_dates = [
            (row, _clean(row.get("amended_date")))
            for row in rrc_records
            if _clean(row.get("amended_date"))
            and re.fullmatch(r"\d{4}-\d{2}-\d{2}", _clean(row.get("amended_date")) or "")
        ]
        if amendment_dates:
            amended_row, amended_date = max(amendment_dates, key=lambda pair: pair[1] or "")
            fields["permit_amended_date"] = amended_date
            permit_event = {
                "kind": "permit_amended",
                "label": "Permit amended",
                "date": amended_date,
                "source": _RRC,
                "evidence_refs": [amended_row["evidence_id"]]
                if amended_row.get("evidence_id")
                else [],
            }
        official_events = [
            event
            for row in valid_official
            for event in row.get("events", [])
            if isinstance(event, dict)
            and event.get("source") in {"texas-rrc-w1-detail", "texas-rrc-completion-packet"}
            and isinstance(event.get("date"), str)
            and re.fullmatch(r"\d{4}-\d{2}-\d{2}", event["date"])
        ]
        for official_event in official_events:
            kind = official_event.get("kind")
            date = official_event.get("date")
            date_fields = {
                "spud": "spud_date",
                "drilling_completion": "drilling_completion_date",
                "rrc_w1_completion_date": "rrc_w1_completion_date",
                "historical_completion": "historical_completion_date",
                "historical_recompletion": "historical_recompletion_date",
            }
            date_field = date_fields.get(kind) if isinstance(kind, str) else None
            if date_field and isinstance(date, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", date):
                fields[date_field] = date
        oil_gas = fields
    elif asset in supported_oil_gas_assets and attributed_oil_gas:
        oil_gas = {
            "relationship_evidence_refs": sorted(
                {str(row["evidence_id"]) for row in valid_relationships}
            )
        }

    is_data_center = bool(
        asset == "data_center" or re.search(r"data cent(?:er|re)|server campus|hyperscale", text)
    )
    sector = "data_centers" if is_data_center else "oil_gas" if oil_gas is not None else "other"
    if sector != "oil_gas":
        oil_gas = None
    owner = _first(compact, "owner", "owner_name", "developer", "developer_name")
    operator = _first(compact, "operator", "operator_name")
    data_center = None
    event = None
    if sector == "data_centers":
        data_center = {}
        for out, keys in {
            "owner_developer": ("owner", "owner_name", "developer", "developer_name"),
            "campus": ("campus", "campus_name", "project_name", "name"),
            "phase": ("phase", "project_phase"),
            "construction_start_date": ("construction_start_date",),
            "energization_date": ("energization_date",),
        }.items():
            value = _first(compact, *keys)
            if value:
                data_center[out] = value
        tdlr_identity = {
            (_clean(row.get("project")), _clean(row.get("owner"))) for row in tdlr_records
        }
        tdlr_consistent = bool(tdlr_records) and len(tdlr_identity) == 1
        if tdlr_consistent:
            row = tdlr_records[0]
            if row.get("owner"):
                data_center["owner_developer"] = row["owner"]
                owner = row["owner"]
            if row.get("project"):
                data_center["campus"] = row["project"].split(" (", 1)[0]
            if row.get("status") and len({_clean(r.get("status")) for r in tdlr_records}) == 1:
                data_center["phase"] = row["status"]
            for out, key in (
                ("registration_date", "registered"),
                ("developer_reported_start_date", "reported_start_date"),
                ("developer_reported_completion_date", "reported_completion_date"),
            ):
                value = _first(row, key)
                if value and re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
                    data_center[out] = value
        # Only use a parsed official record whose exact identifiers were validated.
        lifecycle = lifecycle_event or compact.get("lifecycle_event")
        if isinstance(lifecycle, dict):
            kind, label, date = (_first(lifecycle, k) for k in ("kind", "label", "date"))
            if kind and label and date:
                event = {
                    "kind": kind,
                    "label": label,
                    "date": date,
                    "source": _first(lifecycle, "source", "source_id"),
                    "evidence_refs": lifecycle.get("evidence_refs", [])
                    if isinstance(lifecycle.get("evidence_refs", []), list)
                    else [],
                }
        if tdlr_consistent and event is None:
            row = tdlr_records[0]
            source = "texas-tdlr-tabs-data-centers"
            if data_center.get("developer_reported_start_date"):
                event = {
                    "kind": "developer_reported_planned_start",
                    "label": "Developer-reported planned start",
                    "date": data_center["developer_reported_start_date"],
                    "source": source,
                    "evidence_refs": [row["evidence_id"]] if row.get("evidence_id") else [],
                }
            elif data_center.get("registration_date"):
                event = {
                    "kind": "project_registered",
                    "label": "Registered with TDLR",
                    "date": data_center["registration_date"],
                    "source": source,
                    "evidence_refs": [row["evidence_id"]] if row.get("evidence_id") else [],
                }
        if tdlr_consistent:
            name = data_center.get("campus") or name
            title = data_center.get("campus") or title
        owner = _first(data_center, "owner_developer")
    elif sector == "oil_gas" and oil_gas:
        operator = _first(oil_gas, "operator") or operator
        if permit_event is None and oil_gas.get("permit_issue_date"):
            ref = next(
                (row for row in evidence if isinstance(row, dict) and row.get("source_id") == _RRC),
                {},
            )
            evidence_ref = ref.get("id") or row.get("evidence_id")
            permit_event = {
                "kind": "permit_issued",
                "label": "Permit issued",
                "date": oil_gas["permit_issue_date"],
                "source": _RRC,
                "evidence_refs": [evidence_ref] if evidence_ref else [],
            }
        event_candidates: list[dict[str, Any]] = []
        for candidate in (lifecycle_event, permit_event):
            if isinstance(candidate, dict):
                event_candidates.append(candidate)
        event = None
        for candidate in event_candidates:
            if event is None or str(candidate.get("date") or "") > str(event.get("date") or ""):
                event = candidate

    card = compact.get("intelligence_card")
    power_summary = _first(compact, "power_summary", "power_relevance_summary")
    if not power_summary and isinstance(card, dict):
        power_summary = _first(card, "power_summary", "power_relevance_summary")
    if sector == "oil_gas" and oil_gas:
        power_summary = power_summary or (
            "Oil and gas asset identified; power demand and timing are not established "
            "by permit evidence."
        )
    elif sector == "data_centers":
        power_summary = power_summary or (
            "Data center project identified; temporary load and any residual power gap "
            "are not established."
        )
    return {
        "sector": sector,
        "name": name,
        "title": title,
        "operator": operator,
        "owner": owner,
        "asset_identity": asset_identity,
        "oil_gas": oil_gas,
        "data_center": data_center,
        "event": event,
        "power_summary": power_summary,
        "location": (
            f"{county_label(str(oil_gas.get('county_code')))} County, TX"
            if oil_gas
            and county_label(str(oil_gas.get("county_code")))
            and str(oil_gas.get("county_code")).isdigit()
            and int(str(oil_gas.get("county_code"))) <= 507
            else compact.get("location")
        ),
    }
