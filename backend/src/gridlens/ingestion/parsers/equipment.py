"""Bounded extraction of explicit O&G equipment schedule rows.

This parser intentionally accepts labeled, line-oriented source examples only.
It does not flatten tables, infer electric drive, or calculate demand.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import cast

from gridlens.domain.equipment_demand import (
    Drive,
    EquipmentClaim,
    EquipmentRole,
    EquipmentState,
    EquipmentType,
    RatingBasis,
    RatingUnit,
)

VERSION = "equipment-schedule-lines-v1"
MAX_INPUT_CHARS = 128_000
MAX_ROWS = 256
MAX_ROW_CHARS = 1_200
MAX_CLAIMS = 128


@dataclass(slots=True)
class ExtractionResult:
    claims: list[EquipmentClaim] = field(default_factory=list)
    issues: list[str] = field(default_factory=list)
    truncated: bool = False
    company: str | None = None
    facility: str | None = None
    as_of: str | None = None


_ID = re.compile(r"\b(?:equipment\s+)?id\s*:\s*([A-Z0-9][A-Z0-9._/-]{0,39})\b", re.I)
_TYPE = re.compile(r"\btype\s*:\s*(compressor|pump)\b", re.I)
_RATING_NUMBER = r"-?(?:\d+|\d{1,3}(?:,\d{3})+)(?:\.\d+)?"
_DRIVE = re.compile(
    r"drive\s*:\s*(no\s+electric|not\s+electric|not\s+yet\s+electric|"
    r"gas(?:oline)?\s+engine|diesel\s+engine|steam(?:\s+turbine)?|electric|unknown)"
    r"(?:\s*\((?:gas(?:oline)?\s+engine|diesel\s+engine|steam(?:\s+turbine)?)\))?",
    re.I,
)
_RATING = re.compile(
    rf"rating\s*:\s*({_RATING_NUMBER})\s*(hp|bhp|kW|MW|kVA)"
    r"(?:\s+(mechanical\s+output|electrical\s+input|nameplate|measured))?",
    re.I,
)
_COUNT = re.compile(r"count\s*:\s*(-?\d+)", re.I)
_OPERATING = re.compile(r"(?:operating|running)\s*:\s*(-?\d+)", re.I)
_EFFICIENCY = re.compile(r"efficiency\s*:\s*(\d+(?:\.\d+)?)(%)?", re.I)
_PF = re.compile(r"(?:power\s*factor|pf)\s*:\s*(\d+(?:\.\d+)?)(%)?", re.I)
_DUTY = re.compile(r"duty\s*fraction\s*:\s*(\d+(?:\.\d+)?)(%)?", re.I)
_PERIOD = re.compile(r"period\s*:\s*(\d+(?:\.\d+)?)\s*(hours?|hrs?)", re.I)
_STATE = re.compile(r"state\s*:\s*(proposed|new|existing|installed|retired|standby|unknown)", re.I)
_ROLE = re.compile(r"role\s*:\s*(duty|standby|unknown)", re.I)
_EFFECTIVE_FROM = re.compile(r"effective\s+from\s*:\s*(\d{4}-\d{2}-\d{2})", re.I)
_EFFECTIVE_UNTIL = re.compile(r"effective\s+until\s*:\s*(\d{4}-\d{2}-\d{2})", re.I)
_COMPANY = re.compile(r"^\s*company\s*:\s*(.{1,160}?)\s*$", re.I | re.M)
_FACILITY = re.compile(r"^\s*facility\s*:\s*(.{1,160}?)\s*$", re.I | re.M)
_ASOF_HEADER = re.compile(r"^\s*as\s+of\s*:\s*(.*?)\s*$", re.I | re.M)
_SCHEDULE_FIELD = re.compile(
    r"\b(?:type|drive|rating|count|operating|running|state|role)\s*:", re.I
)

_FIELD_PATTERNS = (
    _ID,
    _TYPE,
    _DRIVE,
    _RATING,
    _COUNT,
    _OPERATING,
    _EFFICIENCY,
    _PF,
    _DUTY,
    _PERIOD,
    _STATE,
    _ROLE,
    _EFFECTIVE_FROM,
    _EFFECTIVE_UNTIL,
)


def _decimal(value: str) -> Decimal | None:
    try:
        return Decimal(value.replace(",", ""))
    except (InvalidOperation, ValueError):
        return None


def _decimal_value(value: str, percent: bool = False) -> Decimal:
    parsed = _decimal(value)
    if parsed is None:
        raise ValueError("invalid decimal")
    sign, digits, exponent = parsed.as_tuple()
    if not isinstance(exponent, int):
        raise ValueError("decimal must be finite")
    return Decimal((sign, digits, exponent - 2 if percent else exponent))


def _one(pattern: re.Pattern[str], text: str) -> re.Match[str] | None:
    matches = list(pattern.finditer(text))
    return matches[0] if len(matches) == 1 else None


def extract_equipment_claims(text: str) -> ExtractionResult:
    """Extract claims from explicit equipment-ID lines, retaining source offsets."""
    result = ExtractionResult()
    if len(text) > MAX_INPUT_CHARS:
        result.truncated = True
        result.issues.append(
            f"Input exceeds {MAX_INPUT_CHARS} character parser bound; extraction abstained."
        )
        return result

    for pattern, field_name in ((_COMPANY, "company"), (_FACILITY, "facility")):
        matches = list(pattern.finditer(text))
        if len(matches) == 1:
            setattr(result, field_name, matches[0].group(1).strip())
        elif len(matches) > 1:
            result.issues.append(f"Multiple {field_name} headers are ambiguous; metadata omitted.")

    asof_headers = list(_ASOF_HEADER.finditer(text))
    if len(asof_headers) == 1:
        value = asof_headers[0].group(1)
        try:
            if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
                raise ValueError("not an ISO date")
            date.fromisoformat(value)
            result.as_of = value
        except ValueError:
            result.issues.append("Invalid as-of date; metadata omitted.")
    elif len(asof_headers) > 1:
        result.issues.append("Multiple as_of headers are ambiguous; metadata omitted.")

    lines = list(re.finditer(r"[^\r\n]+", text))
    if len(lines) > MAX_ROWS:
        result.truncated = True
        result.issues.append(f"Input exceeds {MAX_ROWS} line bound; extraction abstained.")
        return result

    seen: set[str] = set()
    id_fingerprints: dict[str, tuple[object, ...]] = {}
    equipment_lines = 0
    for line_match in lines:
        line = line_match.group(0)
        if not re.search(r"\b(?:equipment\s+)?id\s*:", line, re.I):
            if _SCHEDULE_FIELD.search(line):
                equipment_lines += 1
                result.issues.append(
                    f"Structured equipment row lacks an ID at offset {line_match.start()}."
                )
            continue
        equipment_lines += 1
        if len(line) > MAX_ROW_CHARS:
            result.issues.append(
                f"Equipment row at offset {line_match.start()} exceeds bound; extraction abstained."
            )
            result.truncated = True
            result.claims.clear()
            return result
        if len(result.claims) >= MAX_CLAIMS:
            result.truncated = True
            result.issues.append(f"Input exceeds {MAX_CLAIMS} claim bound; remaining rows omitted.")
            break

        segments = [segment.strip() for segment in line.split("|")]
        parsed: dict[re.Pattern[str], re.Match[str]] = {}
        malformed = False
        for segment in segments:
            match_pair = next(
                (
                    (pattern, match)
                    for pattern in _FIELD_PATTERNS
                    if (match := pattern.fullmatch(segment)) is not None
                ),
                None,
            )
            if match_pair is None:
                malformed = True
                break
            pattern, matched = match_pair
            if pattern in parsed:
                malformed = True
                break
            parsed[pattern] = matched
        if malformed:
            result.issues.append(
                f"Unrecognized or ambiguous equipment row at offset {line_match.start()}."
            )
            continue
        id_match = parsed.get(_ID)
        type_match = parsed.get(_TYPE)
        drive_match = parsed.get(_DRIVE)
        rating_match = parsed.get(_RATING)
        if id_match is None or type_match is None or drive_match is None or rating_match is None:
            result.issues.append(
                f"Unrecognized or ambiguous equipment row at offset {line_match.start()}."
            )
            continue
        quote = line.strip()
        if quote in seen:
            continue
        seen.add(quote)

        rating = _decimal(rating_match.group(1))
        if rating is None or rating <= 0:
            result.issues.append(
                f"Invalid non-positive equipment rating at offset {line_match.start()}."
            )
            continue
        unit_token = rating_match.group(2).casefold()
        unit = {"bhp": "hp", "hp": "hp", "kw": "kW", "mw": "MW", "kva": "kVA"}[unit_token]
        basis_text = (rating_match.group(3) or "").casefold()
        basis = "mechanical_output" if basis_text == "mechanical output" else "unknown"
        if basis_text == "electrical input" and unit != "hp":
            basis = "electrical_input"
        drive_text = drive_match.group(1).casefold()
        drive_suffix = drive_match.group(0).partition("(")[2]
        if drive_suffix and drive_text not in {"no electric", "not electric", "not yet electric"}:
            result.issues.append(f"Contradictory drive annotation at offset {line_match.start()}.")
            continue
        drive = (
            "electric"
            if drive_text == "electric"
            else "gas_engine"
            if drive_text in {"gas engine", "gasoline engine"}
            else "diesel_engine"
            if drive_text == "diesel engine"
            else "steam"
            if drive_text.startswith("steam")
            else "unknown"
        )
        if drive_text in {"no electric", "not electric", "not yet electric"}:
            annotation = drive_match.group(0).partition(":")[2]
            if re.search(r"\bgas(?:oline)?\s+engine\b", annotation, re.I):
                drive = "gas_engine"
            elif re.search(r"\bdiesel\s+engine\b", annotation, re.I):
                drive = "diesel_engine"
            elif re.search(r"\bsteam(?:\s+turbine)?\b", annotation, re.I):
                drive = "steam"
            else:
                drive = "unknown"
        count_match = parsed.get(_COUNT)
        operating_match = parsed.get(_OPERATING)
        efficiency_match = parsed.get(_EFFICIENCY)
        pf_match = parsed.get(_PF)
        duty_match = parsed.get(_DUTY)
        period_match = parsed.get(_PERIOD)
        state_match = parsed.get(_STATE)
        role_match = parsed.get(_ROLE)
        effective_from_match = parsed.get(_EFFECTIVE_FROM)
        effective_until_match = parsed.get(_EFFECTIVE_UNTIL)
        start = line_match.start() + len(line) - len(line.lstrip())
        end = start + len(quote)
        try:
            claim = EquipmentClaim(
                equipment_id=id_match.group(1),
                equipment_type=cast(EquipmentType, type_match.group(1).casefold()),
                drive=cast(Drive, drive),
                rating=rating,
                unit=cast(RatingUnit, unit),
                rating_basis=cast(RatingBasis, basis),
                count=int(count_match.group(1)) if count_match else None,
                efficiency=(
                    _decimal_value(efficiency_match.group(1), bool(efficiency_match.group(2)))
                    if efficiency_match
                    else None
                ),
                power_factor=(
                    _decimal_value(pf_match.group(1), bool(pf_match.group(2))) if pf_match else None
                ),
                state=cast(
                    EquipmentState,
                    state_match.group(1).casefold() if state_match else "unknown",
                ),
                role=cast(
                    EquipmentRole,
                    role_match.group(1).casefold() if role_match else "unknown",
                ),
                operating_count=int(operating_match.group(1)) if operating_match else None,
                duty_fraction=(
                    _decimal_value(duty_match.group(1), bool(duty_match.group(2)))
                    if duty_match
                    else None
                ),
                period_hours=_decimal(period_match.group(1)) if period_match else None,
                quote=quote,
                start=start,
                end=end,
                effective_from=(
                    date.fromisoformat(effective_from_match.group(1))
                    if effective_from_match
                    else None
                ),
                effective_until=(
                    date.fromisoformat(effective_until_match.group(1))
                    if effective_until_match
                    else None
                ),
            )
        except ValueError as exc:
            result.issues.append(f"Invalid equipment fields at offset {line_match.start()}: {exc}.")
            continue
        fingerprint = (
            claim.equipment_type,
            claim.drive,
            claim.rating,
            claim.unit,
            claim.rating_basis,
            claim.count,
        )
        previous = id_fingerprints.get(claim.equipment_id.casefold())
        if previous is not None and previous != fingerprint:
            result.issues.append(
                f"Conflicting claims for equipment ID {claim.equipment_id} were preserved."
            )
        id_fingerprints[claim.equipment_id.casefold()] = fingerprint
        result.claims.append(claim)

    if equipment_lines == 0 and any(
        term in text.casefold() for term in ("pump", "compressor", "compression")
    ):
        result.issues.append(
            "Equipment-like prose lacks an explicit equipment ID and was not extracted."
        )
    return result
