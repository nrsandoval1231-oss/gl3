"""Deterministic commercial screening; never writes qualification or infers load."""

import hashlib
import re
from datetime import date

from gridlens.domain.pursuits import POLICY_VERSION


def normalized(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.casefold()).strip()


def work_identity(source_id: str, external_id: str, site: str) -> str:
    # BP/EP of the exact same official case at the same full unit/building address
    # can share a workspace. Address alone and company names never join work.
    case = re.fullmatch(r"(\d{4}-\d{6}) (?:BP|EP|MP|PP)", external_id)
    key = case[1] if source_id == "austin-building-permits" and case and site else external_id
    return source_id + ":" + hashlib.sha256(f"{key}|{normalized(site)}".encode()).hexdigest()


def screen(facts: list[dict[str, str]], source_id: str, today: date) -> dict:
    scopes = [r.get("description", "") for r in facts]
    text = "\n".join(scopes).casefold()
    organizations = [r.get("contractor_company_name", r.get("operator", "")) for r in facts]
    statuses = [normalized(r.get("status", "")) for r in facts]
    issue_dates = [r.get("date", "")[:10] for r in facts]
    dates = [date.fromisoformat(v) for v in issue_dates if re.fullmatch(r"\d{4}-\d{2}-\d{2}", v)]
    negative = None
    if any(
        re.search(
            r"\b(?:re[ -]?rent(?:er|al|ing)?|equipment rentals?|generator rentals?)\b", o, re.I
        )
        for o in organizations
    ):
        negative = "Permit-listed target is a rental intermediary; exclude re-renters."
    elif any(
        s
        in {
            "final",
            "finaled",
            "completed",
            "closed",
            "expired",
            "cancelled",
            "canceled",
            "withdrawn",
            "void",
            "denied",
        }
        for s in statuses
    ):
        negative = "Official work status is completed, closed, expired or cancelled."
    elif re.search(
        (
            r"\b(?:power package|temporary power|generator rental|power "
            r"supply)\b.{0,60}\b(?:secured|fully awarded|supplied|covered)\b"
        ),
        text,
    ):
        negative = (
            "The described power package is secured or supplied; no remaining scope is evidenced."
        )
    elif re.search(r"\b(?:routine repair|like.for.like|repair only|maintenance only)\b", text):
        negative = "Scope is routine repair or maintenance without evidenced new power work."
    elif dates and max(dates) < date(today.year - 2, today.month, min(today.day, 28)):
        negative = (
            "Historical permit issuance requires current-work proof; suppress "
            "from today's pursuits."
        )
    explicit = bool(
        re.search(
            (
                r"(?:construction power|temporary.{0,40}(?:service|power)|(?:crane|"
                r"hoist).{0,40}(?:service|power)|commissioning.{0,30}(?:power|"
                r"generator|load bank)|bridge power)"
            ),
            text,
        )
    )
    data_center = bool(re.search(r"data[ -]cent(?:er|re)", text))
    utility = bool(re.search(r"transformer|energiz|temporary service", text))
    new_utility = utility and bool(
        re.search(
            r"\b(?:new construction|new building|expansion|install(?:ing|ation)? "
            r"new transformer|new (?:utility|electrical) service|initial energization)\b",
            text,
        )
    )
    fixed = source_id == "texas-rrc-drilling-permits" and any(
        re.search(
            r"\b(?:SWD|saltwater disposal|compress(?:or|ion)|processing)\b",
            r.get("lease", "") + " " + r.get("description", ""),
            re.I,
        )
        for r in facts
    )
    scope = (
        4
        if explicit
        else 3
        if data_center and utility
        else 2
        if data_center or "commissioning" in text or new_utility
        else 1
        if fixed or "light manufacturing" in text
        else 0
    )
    reasons = [
        (
            "Explicit construction/temporary-service or commissioning power "
            "scope; rental demand remains unverified."
        )
        if explicit
        else "Data-center work with utility/transformer scope; no utility delay is established."
        if data_center and utility
        else "Specific data-center/commissioning work warrants power qualification."
        if data_center or "commissioning" in text
        else "New construction/energization scope; utility delay and rental demand remain unknown."
        if new_utility
        else (
            "Named fixed O&G asset approval; construction, startup and power "
            "demand remain unverified."
        )
        if fixed
        else (
            "Specific manufacturing work; interruption or construction power "
            "still needs verification."
        )
        if scope
        else "No specific temporary-power or fixed-asset trigger in retained scope."
    ]
    if negative:
        reasons.insert(0, negative)
    timing = int(bool(dates and (today - max(dates)).days <= 180))
    # A dated permit is permitting evidence, never confirmation of construction.
    if timing:
        reasons.append("Permit issued within 180 days; work start is not confirmed.")
    return {
        "policy_version": POLICY_VERSION,
        "scope_priority": scope,
        "timing_priority": timing,
        "drop_reason": negative,
        "ranking_reasons": reasons,
        "fixed_asset": fixed,
        "explicit_power": explicit,
    }
