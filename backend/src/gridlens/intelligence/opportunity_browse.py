"""Canonical public-browse grouping, matching, and cohort tokens."""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from collections import Counter
from typing import Any

_PERMIT_SOURCE = re.compile(r"-building-permits$")
_JS_WHITESPACE = re.compile(
    r"[\x09-\x0d\x20\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000\ufeff]+"
)
_EXPLICIT_DATE = re.compile(
    r"\b(?:20\d{2}[/-]\d{1,2}[/-]\d{1,2}|"
    r"(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|"
    r"jul(?:y)?|aug(?:ust)?|sep(?:tember)?|oct(?:ober)?|nov(?:ember)?|"
    r"dec(?:ember)?)\.?\s+\d{1,2}(?:-\d{1,2})?,?\s+20\d{2})\b",
    re.I,
)
_EXPLICIT_PLACE = re.compile(
    r"\b(?:in|at)\s+(?:the\s+)?([A-Z][\w&.'’-]*(?:\s+[A-Z][\w&.'’-]*){1,4})"
)
_STRUCTURED_FIELD = re.compile(r"^\s*([a-z][a-z _-]*)\s*:\s*(.*?)\s*$", re.I)
_EMPTY_DESCRIPTION = re.compile(
    r"^(?:n/?a|none|null|unknown|new|building permit|permit|addition|alteration|"
    r"addition\s*/\s*alteration|[-–—])$",
    re.I,
)
_RRC_SOURCE_ID = "texas-rrc-drilling-permits"
_RRC_OPERATOR_PLACEHOLDERS = {"n/a", "na", "none", "null", "unknown", "unavailable"}
_OIL_GAS_CONTEXT = re.compile(
    r"\b(?:oilfield|oil field|oil well|gas well|oil production|gas production|"
    r"upstream oil|upstream gas|natural gas gathering|gas gathering system|"
    r"associated gas|saltwater disposal|produced water|swd facility|"
    r"crude oil pipeline|oil transmission pipeline|natural gas liquids|ngl processing|"
    r"gas processing plant|oilfield electrification|oil and gas field electrification)\b",
    re.I,
)
_NON_OIL_GAS_CONTEXT = re.compile(
    r"\b(?:municipal|water utility|electric utility|public utility|"
    r"air separation|industrial gas|gas distribution utility|local distribution)\b",
    re.I,
)


def normalized(value: Any) -> str:
    text = unicodedata.normalize("NFKC", str(value or ""))
    return _JS_WHITESPACE.sub(" ", text).strip(" ").lower()


def normalized_dimension(value: Any) -> str:
    """Normalize exact displayed filter dimensions without guessing aliases."""
    text = unicodedata.normalize("NFKC", str(value or ""))
    return _JS_WHITESPACE.sub(" ", text).strip(" ").casefold()


def structured_permit_descriptions(abstract: str | None) -> list[str]:
    if not abstract:
        return []
    description = ""
    structured = False
    for line in abstract.splitlines():
        match = _STRUCTURED_FIELD.match(line)
        if not match:
            continue
        structured = True
        label = re.sub(r"[ _-]+", " ", match.group(1).casefold())
        if label == "description" and match.group(2):
            description = match.group(2)
    if not structured:
        return [abstract]
    clean = description.strip()
    return [clean] if clean and not _EMPTY_DESCRIPTION.fullmatch(clean) else []


def _permit_work_title(action: str) -> str:
    work = " ".join(action.split())
    if "|" in work:
        work = work.split("|")[-1].strip()
    replacements = (
        (r"^\(?\d{4}[/-]\d{1,2}[/-]\d{1,2}\)?\s*[|:)–-]*\s*", ""),
        (r"^ePlan:\s*Commercial Expedited Review\s*-\s*", ""),
        (r"^(?:DDS\s+)?20\d{2}\s+CBRC(?:\s*&\s*CBC)?:\s*", ""),
        (r"^SPR\s*/\s*20\d{2}\s+CBC:\s*", ""),
        (r"^PERMIT EXPIRES ON[^.]*\.\s*", ""),
        (r"^ERECTION STARTS:[^.]*?ERECTION ENDS:[^.]*\.\s*", ""),
        (r"^20\d{2}\s+CBC[.: -]*\s*", ""),
        (r"^(?:SELF CERT\s*)?CBC\s*20\d{2}[.: -]*\s*", ""),
        (r"^REINSTATEMENT OF \d{4} PERMIT \d+\s+FOR THE\s+", ""),
        (r"^REINST(?:ATEMENT)? OF \d{4} PERMIT \d+\s+FOR THE\s+", ""),
        (r"\b(?:SELF CERT|SELF-CERT|CBC\s*20\d{2}|2019 CBC)\b", ""),
        (r"\bIntl\.", "International"),
        (r"\bSept\.", "September"),
        (r"\bSt\.(?=\s)", "St"),
    )
    for pattern, replacement in replacements:
        work = re.sub(pattern, replacement, work, flags=re.I)
    work = re.sub(r"\s+", " ", work)
    work = re.sub(r"\bON ON\b", "ON", work, flags=re.I).strip()
    first_clause = re.split(
        r"\.(?:\s|$)|\s+AS PER PLANS\b|\s+CONSTRUCTION TYPE\b",
        work,
        maxsplit=1,
        flags=re.I,
    )[0]
    work = first_clause or work
    work = re.sub(r"\s*\(\s*[\d,.]+\s*SF\s*\).*$", "", work, flags=re.I)
    work = re.sub(r"^[\s,.:;–-]+|[\s,.:;–-]+$", "", work)
    if (
        not work
        or work.isdigit()
        or re.match(r"^(?:row|date|status|document number)\s*:", work, re.I)
        or re.match(
            r"^(?:new|building permit|permit|addition|alteration|addition\s*/\s*alteration)$",
            work,
            re.I,
        )
    ):
        return ""
    acronyms = {"ai", "ats", "cbc", "cbrc", "dc", "mep", "ng", "pacu", "sl100"}

    def title_word(match: re.Match[str]) -> str:
        word = match.group(0)
        return word.upper() if word.casefold() in acronyms else word[:1].upper() + word[1:].lower()

    titled = re.sub(r"\b[a-z0-9]+\b", title_word, work, flags=re.I)
    return f"{titled[:89].rstrip()}…" if len(titled) > 92 else titled


def _action_candidates(item: dict[str, Any]) -> list[str]:
    values: list[str] = []
    supported = str(item.get("supported_action") or "").strip()
    if supported:
        values.append(supported)
    values.extend(item.get("_browse_action_candidates", []))
    return values


def add_browse_evidence(item: dict[str, Any], evidence: dict[str, Any]) -> None:
    """Fold one retained evidence row into only the browse metadata needed downstream."""
    if not item.get("_browse_first_evidence"):
        item["_browse_first_evidence"] = {
            "id": evidence.get("id"),
            "source_id": evidence.get("source_id"),
            "document_number": evidence.get("document_number"),
        }
    abstract = str(evidence.get("abstract") or "")
    if evidence.get("assessment_current"):
        for match in re.finditer(
            r"^\s*(owner_company_name|operator_company_name|applicant_org|"
            r"contractor_company_name|lp_business_name)\s*:\s*(.+?)\s*$",
            abstract,
            re.I | re.M,
        ):
            key = match.group(1).casefold()
            candidates = item.setdefault("_browse_company_candidates", {}).setdefault(key, [])
            candidates.append(match.group(2).strip())
        if evidence.get("source_id") == _RRC_SOURCE_ID:
            # Keep only literal, typed RRC fields needed for a useful well
            # identity. Opaque child bytes remain evidence and are never parsed.
            rrc_values: dict[str, list[str]] = {}
            for line in abstract.splitlines():
                rrc_match = re.fullmatch(
                    r"\s*(operator|operator_number|lease|well|county_code|status|date|permit_issue_date|amended_date)\s*:\s*(.*?)\s*",
                    line,
                    re.I,
                )
                if rrc_match:
                    key, value = rrc_match.group(1).casefold(), rrc_match.group(2).strip()
                    if value and normalized(value) not in _RRC_OPERATOR_PLACEHOLDERS:
                        rrc_values.setdefault(key, []).append(value)
            for operator in rrc_values.get("operator", []):
                item.setdefault("_browse_rrc_operator_candidates", []).append(operator)
            rrc_fields = {
                key: values[0] for key, values in rrc_values.items() if len(set(values)) == 1
            }
            if rrc_fields and not any(len(set(values)) > 1 for values in rrc_values.values()):
                record = {
                    **rrc_fields,
                    "evidence_id": evidence.get("id"),
                    "source_id": _RRC_SOURCE_ID,
                    "document_number": evidence.get("document_number"),
                }
                item.setdefault("_browse_rrc_records", []).append(record)
        elif evidence.get("source_id") == "texas-tdlr-tabs-data-centers":
            fields: dict[str, str] = {}
            for line in abstract.splitlines():
                tdlr_match = re.fullmatch(
                    r"\s*(Project|Registered|Owner|TABS status):\s*(.*?)\s*", line
                )
                if tdlr_match:
                    key, value = tdlr_match.group(1), tdlr_match.group(2).strip()
                    if value and value.casefold() not in {"unknown", "not stated", "none"}:
                        fields[key] = value
                timing_match = re.fullmatch(
                    r"\s*Developer-reported start:\s*(\d{4}-\d{2}-\d{2}|unknown);\s*"
                    r"completion:\s*(\d{4}-\d{2}-\d{2}|unknown)\s*",
                    line,
                    re.I,
                )
                if timing_match:
                    if timing_match.group(1).casefold() != "unknown":
                        fields["reported_start_date"] = timing_match.group(1)
                    if timing_match.group(2).casefold() != "unknown":
                        fields["reported_completion_date"] = timing_match.group(2)
            if fields:
                item.setdefault("_browse_tdlr_records", []).append(
                    {
                        "source_id": "texas-tdlr-tabs-data-centers",
                        "evidence_id": evidence.get("id"),
                        "document_number": evidence.get("document_number"),
                        "project": fields.get("Project"),
                        "registered": fields.get("Registered"),
                        "owner": fields.get("Owner"),
                        "status": fields.get("TABS status"),
                        "reported_start_date": fields.get("reported_start_date"),
                        "reported_completion_date": fields.get("reported_completion_date"),
                    }
                )
        context_text = " ".join((str(evidence.get("title") or ""), abstract))
        context_matches = sorted(
            {match.group(0).casefold() for match in _OIL_GAS_CONTEXT.finditer(context_text)}
        )
        if context_matches and not _NON_OIL_GAS_CONTEXT.search(context_text):
            item.setdefault("_browse_oil_gas_relationship", []).append(
                {
                    "verified": True,
                    "source_id": evidence.get("source_id"),
                    "evidence_id": evidence.get("id"),
                    "document_number": evidence.get("document_number"),
                    "matched_context": context_matches,
                }
            )
    candidates = item.setdefault("_browse_action_candidates", [])
    if candidates and any(_permit_work_title(value) for value in candidates if value):
        return
    descriptions = structured_permit_descriptions(abstract)
    for description in descriptions:
        if _permit_work_title(description) or _action_has_place_and_date(description):
            candidates.append(description)
            return
    if descriptions and not item.get("_browse_fallback_action"):
        item["_browse_fallback_action"] = descriptions[0]
        if not candidates:
            candidates.append(descriptions[0])


def _action_has_place_and_date(action: str) -> bool:
    return bool(_EXPLICIT_DATE.search(action) and _EXPLICIT_PLACE.search(action))


def _reported_action(item: dict[str, Any]) -> str:
    candidates = _action_candidates(item)
    return next(
        (
            candidate
            for candidate in candidates
            if _permit_work_title(candidate) or _action_has_place_and_date(candidate)
        ),
        candidates[0] if candidates else "",
    )


def _neutral_title(item: dict[str, Any]) -> str:
    labels = {
        "backup-power": "Backup power",
        "event-power": "Event power",
        "facility-expansion": "Facility expansion",
        "temporary-power": "Temporary power",
    }
    activity = str(item.get("activity") or "")
    title = labels.get(
        activity, " ".join(part.capitalize() for part in activity.replace("-", " ").split())
    )
    return f"{title} · {item.get('location') or 'Location unknown'}"


def _georgia_title(item: dict[str, Any]) -> str:
    text = " ".join(str(item.get("supported_action") or "").split())
    rules = (
        (
            r"operations will be powered with [^.]{0,160}generator sets?"
            r"[^.]{0,120}until grid power is available",
            "Generators until grid power is available",
        ),
        (
            r"increasing the permitted production[^.]{0,100}(?:quarry|crushing)",
            "Quarry production capacity increase",
        ),
        (
            r"modification and operation of this existing quarry",
            "Quarry processing equipment modification",
        ),
        (
            r"adding a [^.]{0,100}portable stone processing plant",
            "Quarry processing equipment expansion",
        ),
        (
            r"replac(?:e|ing) the existing permitted drum dryer and baghouse",
            "Asphalt plant equipment replacement",
        ),
        (r"additional \d+ emergency generators", "Additional emergency generators"),
        (
            r"construction and operation of a [^.]{0,160}(?:landfill gas|LFG)"
            r"[^.]{0,80}renewable natural gas[^.]{0,80}processing facility",
            "Renewable natural gas facility construction",
        ),
        (
            r"construction and operation of diesel-fired emergency generators to provide "
            r"backup power at a new data center",
            "New data center backup generators",
        ),
        (
            r"construction and operation of a greenfield data center with \d+",
            "New data center construction",
        ),
        (
            r"construction and operation of diesel emergency generators and diesel "
            r"supporting emergency engines at a data processing facility",
            "Data center backup generator installation",
        ),
        (
            r"(?:construct|construction of) (?:a )?(?:new )?"
            r"(?:data center|data processing facility)",
            "New data center construction",
        ),
        (
            r"(?:construct|construction of) (?:a )?(?:new )?(?:facility|data processing facility)",
            "New facility construction",
        ),
        (r"(?:expand|expansion of) (?:the )?(?:facility|campus|data center)", "Facility expansion"),
        (
            r"(?:standby|backup) (?:diesel |natural gas )?generators?",
            "Standby generator installation",
        ),
        (
            r"(?:construct|construction of) [^.]{0,90}(?:plant|mill|quarry|terminal|facility)",
            "Facility construction",
        ),
    )
    for pattern, title in rules:
        if re.search(pattern, text, re.I):
            return title
    return _neutral_title(item)


def project_title(item: dict[str, Any]) -> str:
    title_company = str(item.get("title_company") or "").strip()
    title_role = str(item.get("title_company_role") or "").strip()
    if title_company and title_role:
        return f"{title_company} · {title_role}"
    rrc_operators = item.get("_browse_rrc_operator_candidates", [])
    rrc_records = item.get("_browse_rrc_records", [])
    identities = {
        (normalized(row.get("operator")), normalized(row.get("lease")), normalized(row.get("well")))
        for row in rrc_records
        if row.get("operator") and row.get("lease") and row.get("well")
    }
    if len(identities) == 1:
        row = next(
            row
            for row in rrc_records
            if row.get("operator") and row.get("lease") and row.get("well")
        )
        return f"{row['operator']} · {row['lease']} · Well {row['well']}"
    unique_rrc_operators = {
        normalized(value): value for value in rrc_operators if normalized(value)
    }
    if len(unique_rrc_operators) == 1:
        operator = next(iter(unique_rrc_operators.values()))
        return f"{operator} · RRC permit-listed operator · buyer authority UNKNOWN"
    for key in (
        "owner_company_name",
        "operator_company_name",
        "applicant_org",
        "lp_business_name",
        "contractor_company_name",
    ):
        for value in item.get("_browse_company_candidates", {}).get(key, []):
            clean = str(value).strip()
            if clean and not re.fullmatch(r"unknown", clean, re.I):
                role = {
                    "owner_company_name": "owner",
                    "operator_company_name": "operator",
                    "applicant_org": "applicant",
                    "lp_business_name": "LP Business Name · role unverified",
                    "contractor_company_name": "contractor",
                }[key]
                return f"{clean} · {role}"
    first = item.get("_browse_first_evidence", {})
    source_id = str(first.get("source_id") or "")
    if source_id == "georgia-air-draft-title-v":
        return _georgia_title(item)
    if re.match(r"^(?:houston\s+)?permit\b", str(item.get("name") or ""), re.I):
        return _neutral_title(item)
    if not _PERMIT_SOURCE.search(source_id):
        return str(item.get("name") or "")
    for action in _action_candidates(item):
        if item.get("activity") == "event-power" and _action_has_place_and_date(action):
            place = _EXPLICIT_PLACE.search(action)
            date_match = re.search(
                r"\b(january|february|march|april|may|june|july|august|september|october|november|december)\b[^|.;]{0,60}\b(20\d{2})\b",
                action,
                re.I,
            )
            year = re.search(r"\b(20\d{2})\b", action)
            date = (
                f"{date_match.group(1)[:3].title()} {date_match.group(2)}"
                if date_match
                else year.group(1)
                if year
                else ""
            )
            work = re.search(
                r"\b(music stages?[^.|]*|food vendors?[^.|]*|art vendors?[^.|]*|"
                r"hospitality programs?[^.|]*)",
                action,
                re.I,
            )
            if place and work:
                label = " ".join(work.group(0).replace("  ", " ").strip(" .;,|").split())
                return f"{place.group(1).rstrip('.,')} · {label.title()}" + (
                    f" · {date}" if date else ""
                )
        title = _permit_work_title(action)
        if title:
            return title
    return _neutral_title(item)


def opportunity_group_key(item: dict[str, Any], shared_project: bool) -> str:
    tier = str(item.get("tier") or "")
    project_id = str(item.get("project_id") or "")
    if shared_project and project_id:
        return f"project:{tier}:{project_id}"
    first = item.get("_browse_first_evidence") or (item.get("evidence") or [{}])[0]
    source_id = str(first.get("source_id") or "")
    action = _reported_action(item)
    if (
        _PERMIT_SOURCE.search(source_id)
        and item.get("location")
        and action
        and _action_has_place_and_date(action)
    ):
        return "\x1f".join(
            (
                source_id,
                normalized(item.get("location")),
                normalized(tier),
                normalized(item.get("activity")),
                normalized(action),
            )
        )
    if project_id:
        return f"project:{tier}:{project_id}"
    return f"record:{item.get('id')}"


def opportunity_group_id(key: str) -> str:
    return "og_" + hashlib.sha256(key.encode("utf-8")).hexdigest()[:40]


def matched_opportunity(
    item: dict[str, Any], query: str, evidence_text_match: bool = False
) -> bool:
    term = normalized(query)
    if not term:
        return True
    fields = (
        item.get("name"),
        project_title(item),
        item.get("location"),
        item.get("activity"),
        item.get("supported_subject"),
        item.get("supported_action"),
        item.get("assessment_reason"),
    )
    searchable = " ".join(normalized(value) for value in fields if value)
    return evidence_text_match or term in searchable


def grouped_signal_decision(members: list[dict[str, Any]]) -> str:
    decisions = [item.get("signal_display_decision") for item in members]
    if "SHOW" in decisions:
        return "SHOW"
    if "REVIEW" in decisions or any(value != "HOLD" for value in decisions):
        return "REVIEW"
    return "HOLD"


def grouped_opportunities(items: list[dict[str, Any]]) -> list[tuple[str, list[dict[str, Any]]]]:
    project_counts = Counter(
        (str(item.get("tier") or ""), str(item.get("project_id") or ""))
        for item in items
        if item.get("project_id")
    )
    groups: dict[str, list[dict[str, Any]]] = {}
    for item in items:
        pair = (str(item.get("tier") or ""), str(item.get("project_id") or ""))
        key = opportunity_group_key(item, bool(pair[1] and project_counts[pair] > 1))
        groups.setdefault(key, []).append(item)
    return list(groups.items())


def cohort_token(filters: dict[str, Any], rows: list[dict[str, Any]], group_keys: list[str]) -> str:
    payload = {
        "filters": {
            key: normalized(value) for key, value in sorted(filters.items()) if value is not None
        },
        "rows": [
            [
                str(row.get("id")),
                str(row.get("_cohort_version") or ""),
                group_keys[index],
                hashlib.sha256(
                    json.dumps(
                        {
                            key: row.get(key)
                            for key in (
                                "project_id",
                                "_cohort_project_identity",
                                "_cohort_active",
                                "tier",
                                "required_mw",
                                "start_window",
                                "name",
                                "location",
                                "activity",
                                "supported_action",
                                "supported_subject",
                                "assessment_reason",
                                "asset_type",
                                "lifecycle_state",
                                "signal_display_decision",
                                "signal_display_decision_state",
                                "signal_display_source",
                                "signal_display_reason",
                                "_priority_features",
                                "_priority_segment",
                                "title_company",
                                "title_company_role",
                                "evidence",
                                "_browse_evidence_fingerprint",
                                "_current_fact_digest",
                                "workflow_status",
                            )
                        },
                        sort_keys=True,
                        separators=(",", ":"),
                        default=str,
                    ).encode("utf-8")
                ).hexdigest(),
            ]
            for index, row in enumerate(rows)
        ],
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()
