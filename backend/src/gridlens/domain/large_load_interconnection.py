"""Source-reported request facts and separate, advisory §25.194 interpretation.

No qualification, lifecycle mutation, supply subtraction or compliance verdicts.
Only callers that bind current accepted Evidence to a Project may supply records.
"""

from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

VERSION = "tx-large-load-v1"
EFFECTIVE_ON = date(2026, 10, 8)
RULE = {
    "citation": "16 TAC §25.194",
    "project": "58481",
    "version": VERSION,
    "published_on": "2026-10-02",
    "effective_on": EFFECTIVE_ON.isoformat(),
    "url": "https://www.sos.texas.gov/texreg/archive/October22026/Adopted%20Rules/"
    "16.ECONOMIC%20REGULATION.html",
    "locations": [
        "§25.194(a)-(b)",
        "§25.194(d)(2)(B)",
        "§25.194(e)",
        "§25.194(f)",
        "§25.194(h)-(i)",
        "TRD-202604027",
    ],
}
BOOL_FIELDS = {
    "ercot_region",
    "energized_as_of_effective_date",
    "colocated_generation",
    "batch_zero",
}
NUMBER_FIELDS = {
    "expected_site_peak_mw",
    "existing_site_peak_mw",
    "allocated_mw",
    "financial_security_usd",
    "study_fee_paid_usd",
}
DATE_FIELDS = {
    "intermediate_executed_on",
    "intermediate_funded_on",
    "allocating_study_report_issued_on",
    "sllia_executed_on",
    "sllia_funded_on",
}
ENUM_FIELDS = {
    "request_kind": {"new", "expanded"},
    "study_state": {"requested", "included", "commenced", "completed", "withdrawn", "cancelled"},
    "financial_security_form": {"cash_collateral", "guaranty", "letter_of_credit"},
    "financial_security_stage": {"intermediate", "sllia", "legacy"},
}
FIELDS = BOOL_FIELDS | NUMBER_FIELDS | DATE_FIELDS | ENUM_FIELDS.keys()


def _value(field: str, value: Any) -> Any:
    if field in BOOL_FIELDS and type(value) is bool:
        return value
    if field in NUMBER_FIELDS and isinstance(value, str | int) and type(value) is not bool:
        number = Decimal(str(value))
        if number.is_finite() and number >= 0:
            return format(number.normalize(), "f")
    if field in DATE_FIELDS and isinstance(value, str):
        parsed = date.fromisoformat(value)
        if parsed.isoformat() == value:
            return value
    if field in ENUM_FIELDS and isinstance(value, str) and value in ENUM_FIELDS[field]:
        return value
    raise ValueError("Invalid typed interconnection fact")


def _interpret(facts: dict, today: date) -> dict:
    def get(field):
        return facts[field]["value"] if facts[field]["status"] == "REPORTED" else None

    ercot, energized, kind = (
        get(k) for k in ("ercot_region", "energized_as_of_effective_date", "request_kind")
    )
    total, existing = get("expected_site_peak_mw"), get("existing_site_peak_mw")
    peak = Decimal(total) if total is not None else None
    prior = Decimal(existing) if existing is not None else None
    applicability, basis, incremental = "UNKNOWN", "Missing or conflicting scope facts", None
    if ercot is False or energized is True:
        applicability, basis = "NOT_APPLICABLE", "Outside ERCOT or energized as of effective date"
    elif ercot is True and energized is False and peak is not None:
        if peak < 75:
            applicability, basis = "NOT_APPLICABLE", "Below large-load single-site definition"
        elif get("colocated_generation") is True:
            applicability, basis = (
                "APPLIES",
                "Large load co-located with generation; §25.194(b)(1)(D)",
            )
        elif kind == "new":
            applicability, basis = "APPLIES", "New single-site load at least 75 MW; (b)(1)(A)"
        elif kind == "expanded" and prior is not None and peak > prior:
            incremental = peak - prior
            if prior < 75 or incremental >= 75:
                applicability, basis = (
                    "APPLIES",
                    "First crossing or at least 75 MW expansion; (b)(1)(B)-(C)",
                )
            elif get("colocated_generation") is False:
                applicability, basis = (
                    "NOT_APPLICABLE",
                    "Existing large load expands by less than 75 MW",
                )
    if kind == "expanded" and peak is not None and prior is not None and peak > prior:
        incremental = peak - prior
    effective = today >= EFFECTIVE_ON
    security_basis = peak if kind == "new" else incremental
    baseline = (
        format(security_basis * 50000, "f")
        if effective
        and applicability == "APPLIES"
        and security_basis is not None
        and get("batch_zero") is not True
        and today.year < 2032
        else None
    )
    report = get("allocating_study_report_issued_on")
    due = (
        date.fromisoformat(report) + timedelta(days=60)
        if effective and applicability == "APPLIES" and report
        else None
    )
    follow_up = "UNKNOWN"
    if due:
        executed, funded = get("sllia_executed_on"), get("sllia_funded_on")
        if executed and funded:
            follow_up = "REPORTED_EXECUTED_AND_FUNDED"
        elif today > due:
            follow_up = "DEADLINE_PASSED_CHECK_EVIDENCE"
        else:
            follow_up = "CHECK_EXECUTION_AND_FUNDING"
    return {
        "value_kind": "derived",
        "rule_in_effect": effective,
        "applicability": applicability,
        "basis": basis,
        "incremental_mw": format(incremental, "f") if incremental is not None else None,
        "intermediate_security_baseline_usd": baseline,
        "security_basis": (
            "Standard intermediate baseline only; not proof posted or total SLLIA security"
        ),
        "transition_review_required": get("batch_zero") is not False,
        "sllia_due_on": due.isoformat() if due else None,
        "sllia_follow_up": follow_up,
        "disclosure": "Advisory rule mapping, not a legal compliance determination. "
        "Pending requests are not automatically exempt. Missing evidence is not noncompliance.",
    }


def interconnection_state(records: list[dict], *, today: date) -> dict:
    """Project/request-scoped evidence records; conflicting values stay unresolved.

    A record contains request_id, retained text, evidence provenance, and typed
    field/value/quote facts. The source admission boundary supplies the project
    binding; this function validates claim shape and keeps provenance per fact.
    """
    requests: dict[str, dict] = {}
    for record in records:
        request_id = record.get("request_id")
        if not isinstance(request_id, str) or not request_id.strip():
            continue
        bucket = requests.setdefault(request_id, {"claims": {}, "limitations": []})
        evidence = record.get("evidence") or {}
        try:
            if not all(
                evidence.get(k)
                for k in (
                    "id",
                    "hash",
                    "url",
                    "published_at",
                    "retrieved_at",
                    "extraction_location",
                )
            ):
                raise ValueError("Missing source provenance")
            if date.fromisoformat(str(evidence["published_at"])) > today:
                raise ValueError("Future publication")
        except (ValueError, TypeError):
            bucket["limitations"].append("Undated, future or incomplete source provenance")
            continue
        reported_facts = record.get("facts")
        if not isinstance(reported_facts, list):
            bucket["limitations"].append("Malformed interconnection facts payload")
            continue
        for claim in reported_facts:
            try:
                field, quote = claim.get("field"), claim.get("quote")
                if field not in FIELDS or not isinstance(quote, str) or not quote.strip():
                    raise ValueError("Invalid field or quote")
                if quote not in (record.get("text") or ""):
                    raise ValueError("Quote absent from retained evidence")
                value = _value(field, claim.get("value"))
                if field in DATE_FIELDS and date.fromisoformat(value) > today:
                    raise ValueError("Future occurrence")
                row = {"value": value, "quote": quote, "evidence": evidence}
                rows = bucket["claims"].setdefault(field, [])
                if row not in rows:
                    rows.append(row)
            except (ValueError, InvalidOperation, TypeError, AttributeError):
                bucket["limitations"].append(
                    "Rejected malformed or unsupported interconnection claim"
                )
    result = []
    for request_id, bucket in sorted(requests.items()):
        facts = {}
        for field in sorted(FIELDS):
            claims = bucket["claims"].get(field, [])
            conflict = bool(claims) and any(c["value"] != claims[0]["value"] for c in claims)
            facts[field] = {
                "value": claims[0]["value"] if claims and not conflict else None,
                "status": "CONFLICT" if conflict else "REPORTED" if claims else "UNKNOWN",
                "claims": claims,
            }
        result.append(
            {
                "request_id": request_id,
                "facts": facts,
                "interpretation": _interpret(facts, today),
                "limitations": sorted(set(bucket["limitations"])),
            }
        )
    return {"rule": RULE, "requests": result}
