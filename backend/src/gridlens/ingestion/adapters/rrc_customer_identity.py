"""Typed operator identity from the two source-native Texas RRC adapters."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

SOURCES = {"texas-rrc-drilling-permits", "texas-rrc-flare-vent-exceptions"}
_PLACEHOLDERS = {"", "n/a", "na", "none", "null", "unknown", "unavailable"}
# RRC operator/P5 numbers are six-digit identifiers; leading zeros are retained.
# Source semantics: RRC EWA glossary and Groundwater Advisory Unit form instructions.
# https://webapps2.rrc.state.tx.us/EWA/help/EWA_Glossary.html
# https://www.rrc.texas.gov/oil-and-gas/applications-and-permits/groundwater-advisory-unit/gau-form-instructions/


@dataclass(frozen=True)
class RrcOperatorIdentity:
    operator_number: str
    operator_name: str


def rrc_operator_identity(source_id: str, record: dict[str, Any]) -> RrcOperatorIdentity | None:
    """Return a strong ID from typed RRC fields or exact source-native retained labels."""
    if source_id not in SOURCES:
        return None
    abstract = str(record.get("abstract") or "")
    permit = record.get("permit")
    number_matches = re.findall(
        r"^(?:Operator number|operator_number):[ \t]*([^\r\n]*)[ \t]*$",
        abstract,
        re.I | re.M,
    )
    name_matches = re.findall(r"^Operator:[ \t]*([^\r\n]*)[ \t]*$", abstract, re.I | re.M)
    if isinstance(permit, dict):
        if permit.get("source_type") != source_id:
            return None
        number = str(permit.get("operator_number") or "").strip()
        name = " ".join(str(permit.get("operator") or "").split())
    else:
        if not number_matches or not name_matches:
            return None
        number = number_matches[0].strip()
        name = " ".join(name_matches[0].split())
    if not re.fullmatch(r"\d{6}", number) or number == "000000" or name.casefold() in _PLACEHOLDERS:
        return None
    # The source-native adapter also emits these exact labeled values into the
    # retained record. Require both before treating the identifier as attributed.
    if not number_matches or any(value.strip() != number for value in number_matches):
        return None
    normalized_names = [" ".join(value.split()) for value in name_matches]
    if not normalized_names or any(value != name for value in normalized_names):
        return None
    return RrcOperatorIdentity(number, name)
