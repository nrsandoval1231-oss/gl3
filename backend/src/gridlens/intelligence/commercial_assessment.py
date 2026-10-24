"""Strict, source-bound validation for the M4 advisory result."""

from __future__ import annotations

import hashlib
import json
from typing import Any

SCHEMA_VERSION = "commercial-assessment-v1"
POLICY_VERSION = "commercial-assessment-policy-v1"
MAX_TEXT = 500

ASSESSMENT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "disposition",
        "reason_code",
        "selected_fact_ids",
        "research_dimensions",
        "next_question_id",
    ],
    "properties": {
        "disposition": {"type": "string", "enum": ["INVESTIGATE", "NOT_SUPPORTED", "UNRESOLVED"]},
        "reason_code": {
            "type": "string",
            "enum": [
                "SOURCE_SUPPORTS_FOLLOWUP",
                "NO_RENTAL_EVIDENCE",
                "EXCERPT_INSUFFICIENT",
                "CONFLICTING_EVIDENCE",
            ],
        },
        "selected_fact_ids": {"type": "array", "items": {"type": "string"}, "maxItems": 12},
        "research_dimensions": {
            "type": "array",
            "items": {
                "type": "string",
                "enum": [
                    "REQUIRED_MW",
                    "START_WINDOW",
                    "BUYER_AUTHORITY",
                    "SUPPLY_GAP",
                    "DURATION",
                    "RENTAL_VS_PERMANENT",
                ],
            },
            "maxItems": 6,
        },
        "next_question_id": {
            "type": ["string", "null"],
            "enum": [
                "UTILITY_ONLINE_DATE",
                "TEMP_LOAD_MW",
                "CONSTRUCTION_START",
                "COMMISSIONING_WINDOW",
                "NATURAL_GAS_AVAILABILITY",
                "DIRECT_BUYER_AUTHORITY",
                None,
            ],
        },
    },
}


def digest(value: Any) -> str:
    raw = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def validate_assessment(
    value: Any,
    *,
    package: dict[str, Any],
    need_id: str,
    project_id: str,
    current_need: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Validate an advisory against the exact source facts in an M3 package."""
    if not isinstance(package, dict) or package.get("processing_status") != "COMPLETE_ADVISORY":
        raise ValueError("PACKAGE_NOT_COMPLETE_ADVISORY")
    if package.get("project_id") != project_id or package.get("need_id") != need_id:
        raise ValueError("PACKAGE_IDENTITY_MISMATCH")
    if not isinstance(value, dict) or set(value) != set(ASSESSMENT_SCHEMA["required"]):
        raise ValueError("ASSESSMENT_SHAPE_INVALID")
    facts = package.get("facts")
    if not isinstance(facts, list):
        raise ValueError("PACKAGE_FACTS_INVALID")
    fact_ids: set[str] = set()
    for fact in facts:
        if not isinstance(fact, dict):
            raise ValueError("PACKAGE_FACTS_INVALID")
        citation = fact.get("citation")
        if (
            not isinstance(citation, dict)
            or not isinstance(citation.get("evidence_id"), str)
            or not isinstance(citation.get("evidence_hash"), str)
            or not isinstance(citation.get("excerpt_location"), dict)
        ):
            raise ValueError("PACKAGE_FACTS_INVALID")
        reference = package.get("source_references")
        span = citation["excerpt_location"]
        if (
            not isinstance(reference, list)
            or len(reference) != 1
            or citation["evidence_id"] != reference[0].get("evidence_id")
            or citation["evidence_hash"] != reference[0].get("evidence_hash")
            or span.get("field") not in {"title", "abstract"}
            or type(span.get("start")) is not int
            or type(span.get("end")) is not int
            or span["start"] < 0
            or span["end"] <= span["start"]
        ):
            raise ValueError("PACKAGE_CITATION_INVALID")
        source_fact = {k: v for k, v in fact.items() if k != "fact_id"}
        fact_ids.add(f"f-{digest(source_fact)[:16]}")
    selected = value["selected_fact_ids"]
    if (
        not isinstance(selected, list)
        or len(selected) > 12
        or not all(isinstance(item, str) for item in selected)
        or len(set(selected)) != len(selected)
        or not set(selected) <= fact_ids
    ):
        raise ValueError("FACT_REFERENCE_INVALID")
    if value["reason_code"] not in {
        "SOURCE_SUPPORTS_FOLLOWUP",
        "NO_RENTAL_EVIDENCE",
        "EXCERPT_INSUFFICIENT",
        "CONFLICTING_EVIDENCE",
    }:
        raise ValueError("REASON_CODE_INVALID")
    allowed_dimensions = set(
        ASSESSMENT_SCHEMA["properties"]["research_dimensions"]["items"]["enum"]
    )
    if (
        not isinstance(value["research_dimensions"], list)
        or len(value["research_dimensions"]) > 6
        or not all(
            isinstance(item, str) and item in allowed_dimensions
            for item in value["research_dimensions"]
        )
        or len(set(value["research_dimensions"])) != len(value["research_dimensions"])
    ):
        raise ValueError("RESEARCH_DIMENSIONS_INVALID")
    question_ids = {
        "UTILITY_ONLINE_DATE",
        "TEMP_LOAD_MW",
        "CONSTRUCTION_START",
        "COMMISSIONING_WINDOW",
        "NATURAL_GAS_AVAILABILITY",
        "DIRECT_BUYER_AUTHORITY",
    }
    if value["next_question_id"] is not None and value["next_question_id"] not in question_ids:
        raise ValueError("NEXT_QUESTION_INVALID")
    if value["disposition"] not in {"INVESTIGATE", "NOT_SUPPORTED", "UNRESOLVED"}:
        raise ValueError("DISPOSITION_INVALID")
    if value["reason_code"] == "EXCERPT_INSUFFICIENT" and value["disposition"] != "UNRESOLVED":
        raise ValueError("PARTIAL_EVIDENCE_MUST_REMAIN_UNRESOLVED")
    if value["reason_code"] == "NO_RENTAL_EVIDENCE" and value["disposition"] != "NOT_SUPPORTED":
        raise ValueError("NO_RENTAL_EVIDENCE_DISPOSITION_MISMATCH")
    if value["disposition"] == "INVESTIGATE" and value["reason_code"] != "SOURCE_SUPPORTS_FOLLOWUP":
        raise ValueError("INVESTIGATE_REQUIRES_FOLLOWUP_BASIS")
    if value["reason_code"] == "CONFLICTING_EVIDENCE" and not package.get("contradiction_pairs"):
        raise ValueError("CONFLICT_REASON_WITHOUT_VALIDATED_CONTRADICTION")
    if value["reason_code"] == "CONFLICTING_EVIDENCE" and value["disposition"] != "UNRESOLVED":
        raise ValueError("CONFLICTING_EVIDENCE_MUST_REMAIN_UNRESOLVED")
    if value["disposition"] == "INVESTIGATE" and not selected:
        raise ValueError("INVESTIGATE_REQUIRES_CITED_FACT")
    result = {
        "schema_version": SCHEMA_VERSION,
        "policy_version": POLICY_VERSION,
        "authority": "ADVISORY_ONLY",
        **value,
    }
    field_map = {
        "required_mw": "REQUIRED_MW",
        "start_window": "START_WINDOW",
        "supply": "SUPPLY_GAP",
        "duration": "DURATION",
    }
    known = {
        field_map[k]
        for k, v in (current_need or {}).items()
        if k in field_map
        and v is not None
        and not (
            isinstance(v, str) and v.strip().casefold() in {"", "unknown", "none", "not reported"}
        )
    }
    known_fields = {
        "required_mw": "REQUIRED_MW",
        "temporary_load_mw": "REQUIRED_MW",
        "start_date": "START_WINDOW",
        "start_window": "START_WINDOW",
        "buyer": "BUYER_AUTHORITY",
        "buyer_authority": "BUYER_AUTHORITY",
        "purchasing_authority": "BUYER_AUTHORITY",
        "supply": "SUPPLY_GAP",
        "duration": "DURATION",
        "rental_demand": "RENTAL_VS_PERMANENT",
        "temporary_power": "RENTAL_VS_PERMANENT",
    }
    accepted = (current_need or {}).get("accepted_facts", [])
    if isinstance(accepted, list):
        for fact in accepted:
            if isinstance(fact, dict):
                name = str(fact.get("fact_type", fact.get("field", ""))).casefold()
                fact_value = fact.get("value")
                if (
                    name in known_fields
                    and fact_value is not None
                    and not (
                        isinstance(fact_value, str)
                        and fact_value.strip().casefold() in {"", "unknown", "none", "not reported"}
                    )
                ):
                    known.add(known_fields[name])
    known.update(
        {"BUYER_AUTHORITY"}
        if any(f.get("field") in {"buyer", "buyer_authority"} for f in facts)
        else set()
    )
    result["unknown_fields"] = sorted(
        set(ASSESSMENT_SCHEMA["properties"]["research_dimensions"]["items"]["enum"]) - known
    )
    if value["next_question_id"]:
        from gridlens.intelligence.question_contracts import question_contract

        result["next_question"] = question_contract(value["next_question_id"])["question"]
    else:
        result["next_question"] = None
    result["next_action"] = (
        "Review the cited evidence and pursue the selected research question."
        if value["next_question_id"]
        else "Retain as unresolved and await additional project-specific evidence."
    )
    result["request_digest"] = digest(
        {
            "need_id": need_id,
            "project_id": project_id,
            "package_key": package.get("package_key"),
            "package": package,
            "schema": SCHEMA_VERSION,
            "policy": POLICY_VERSION,
            "model": "gpt-6.1-sol",
        }
    )
    result["result_digest"] = digest(result)
    return result
