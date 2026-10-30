"""Deterministic, provenance-preserving equipment demand arithmetic."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, fields
from datetime import date, datetime
from decimal import ROUND_HALF_EVEN, Context, Decimal, localcontext
from hashlib import sha256
from typing import Literal

EquipmentType = Literal["compressor", "pump"]
Drive = Literal["electric", "gas_engine", "diesel_engine", "steam", "unknown"]
RatingUnit = Literal["hp", "kW", "MW", "kVA"]
RatingBasis = Literal["mechanical_output", "electrical_input", "unknown"]
EquipmentState = Literal["proposed", "new", "existing", "installed", "retired", "unknown"]
EquipmentRole = Literal["duty", "standby", "unknown"]

HP_TO_KW = Decimal("0.745699872")
MODEL_ID = "gridlens.equipment_demand"
MODEL_VERSION = "1.0.0"
DEMAND_CONTEXT = Context(prec=28, rounding=ROUND_HALF_EVEN)


@dataclass(frozen=True, slots=True)
class EquipmentClaim:
    equipment_id: str
    equipment_type: EquipmentType
    drive: Drive
    rating: Decimal | None
    unit: RatingUnit
    rating_basis: RatingBasis
    count: int | None
    efficiency: Decimal | None = None
    power_factor: Decimal | None = None
    state: EquipmentState = "unknown"
    role: EquipmentRole = "unknown"
    operating_count: int | None = None
    duty_fraction: Decimal | None = None
    period_hours: Decimal | None = None
    quote: str = ""
    source_id: str = ""
    start: int | None = None
    end: int | None = None
    effective_from: date | None = None
    effective_until: date | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.equipment_id, str) or not self.equipment_id.strip():
            raise ValueError("equipment_id is required")
        allowed = {
            "equipment_type": {"compressor", "pump"},
            "drive": {"electric", "gas_engine", "diesel_engine", "steam", "unknown"},
            "unit": {"hp", "kW", "MW", "kVA"},
            "rating_basis": {"mechanical_output", "electrical_input", "unknown"},
            "state": {"proposed", "new", "existing", "installed", "retired", "unknown"},
            "role": {"duty", "standby", "unknown"},
        }
        for field, values in allowed.items():
            if getattr(self, field) not in values:
                raise ValueError(f"{field} has an unsupported value")
        if self.unit == "hp" and self.rating_basis == "electrical_input":
            raise ValueError("horsepower cannot describe an electrical input rating")
        if self.unit == "kVA" and self.rating_basis == "mechanical_output":
            raise ValueError("kVA cannot describe a mechanical output rating")
        if (
            self.drive in ("gas_engine", "diesel_engine", "steam")
            and self.rating_basis == "electrical_input"
        ):
            raise ValueError("non-electric drive cannot claim electrical motor input")
        if any(
            value is not None and (not isinstance(value, int) or isinstance(value, bool))
            for value in (self.count, self.operating_count)
        ):
            raise ValueError("counts must be integers")
        if self.count is not None and self.count < 0:
            raise ValueError("count must be a nonnegative integer or unknown")
        if self.operating_count is not None and self.operating_count < 0:
            raise ValueError("operating_count must be a nonnegative integer or unknown")
        if any(
            value is not None and value > 100_000 for value in (self.count, self.operating_count)
        ):
            raise ValueError("counts exceed the supported bound")
        if self.count is not None and self.operating_count is not None:
            if self.operating_count > self.count:
                raise ValueError("operating_count cannot exceed count")
        if self.role == "standby" and self.operating_count not in (None, 0):
            raise ValueError("standby equipment cannot have positive normal operating_count")
        if any(
            value is not None and (not isinstance(value, int) or isinstance(value, bool))
            for value in (self.start, self.end)
        ):
            raise ValueError("source span offsets must be integers")
        if (self.start is None) != (self.end is None):
            raise ValueError("source span requires both start and end offsets")
        if self.start is not None and (self.start < 0 or self.end is None or self.end < self.start):
            raise ValueError("source span offsets are invalid")
        _bounded_decimal(self.rating, "rating", maximum=Decimal("1000000000"))
        _bounded_decimal(
            self.efficiency, "efficiency", minimum_exclusive=Decimal(0), maximum=Decimal(1)
        )
        _bounded_decimal(
            self.power_factor, "power_factor", minimum_exclusive=Decimal(0), maximum=Decimal(1)
        )
        _bounded_decimal(self.duty_fraction, "duty_fraction", maximum=Decimal(1))
        _bounded_decimal(self.period_hours, "period_hours", maximum=Decimal("87600"))
        if any(
            value is not None and (not isinstance(value, date) or isinstance(value, datetime))
            for value in (self.effective_from, self.effective_until)
        ):
            raise ValueError("effective dates must be date values")
        if (
            self.effective_from is not None
            and self.effective_until is not None
            and self.effective_until < self.effective_from
        ):
            raise ValueError("effective_until must not precede effective_from")
        if not isinstance(self.quote, str) or len(self.quote) > 4000:
            raise ValueError("quote must be at most 4000 characters")
        if not isinstance(self.source_id, str):
            raise ValueError("source_id must be a string")


def _bounded_decimal(
    value: Decimal | None,
    field: str,
    *,
    minimum_exclusive: Decimal | None = None,
    maximum: Decimal,
) -> None:
    if value is None:
        return
    if not isinstance(value, Decimal) or not value.is_finite() or value > maximum:
        raise ValueError(f"{field} must be a finite supported Decimal")
    decimal_tuple = value.as_tuple()
    exponent = decimal_tuple.exponent
    if not isinstance(exponent, int):
        raise ValueError(f"{field} must be finite")
    if len(decimal_tuple.digits) > 64 or not -100 <= exponent <= 100:
        raise ValueError(f"{field} exceeds supported Decimal precision or scale")
    if minimum_exclusive is not None and value <= minimum_exclusive:
        raise ValueError(f"{field} must be greater than {minimum_exclusive}")
    if minimum_exclusive is None and value < 0:
        raise ValueError(f"{field} must be nonnegative")


@dataclass(frozen=True, slots=True)
class EquipmentDemandItem:
    equipment_id: str
    mechanical_kw: Decimal | None
    electrical_input_kw: Decimal | None
    connected_kw: Decimal | None
    coincident_kw: Decimal | None
    incremental_kw: Decimal | None
    energy_mwh: Decimal | None
    average_kw: Decimal | None
    status: Literal["known", "unknown", "conflicted"]
    input_hash: str


@dataclass(frozen=True, slots=True)
class EquipmentDemandResult:
    model_id: str
    model_version: str
    as_of: date | datetime | None
    inputs: tuple[EquipmentClaim, ...]
    input_hashes: tuple[str, ...]
    items: tuple[EquipmentDemandItem, ...]
    mechanical_kw: Decimal | None
    electrical_input_kw: Decimal | None
    connected_kw: Decimal | None
    coincident_kw: Decimal | None
    incremental_kw: Decimal | None
    energy_mwh: Decimal | None
    average_kw: Decimal | None
    known_connected_subtotal_kw: Decimal | None
    unresolved: tuple[str, ...] = ()


def _unit_kw(claim: EquipmentClaim) -> Decimal | None:
    if claim.rating is None:
        return None
    with localcontext(DEMAND_CONTEXT) as context:
        context.prec = 28
        if claim.unit == "hp":
            return claim.rating * HP_TO_KW
        if claim.unit == "kW":
            return +claim.rating
        if claim.unit == "MW":
            return claim.rating * Decimal(1000)
        if claim.unit == "kVA":
            if claim.power_factor is None:
                return None
            return claim.rating * claim.power_factor
        return None


def _item(claim: EquipmentClaim, as_of: date | datetime | None) -> EquipmentDemandItem:
    active = not (
        claim.state == "retired"
        or (
            as_of is not None
            and claim.effective_until is not None
            and claim.effective_until < (as_of.date() if isinstance(as_of, datetime) else as_of)
        )
    )
    mechanical = None
    electrical = None
    with localcontext(DEMAND_CONTEXT) as context:
        context.prec = 28
        if claim.drive in ("gas_engine", "diesel_engine", "steam"):
            mechanical = _unit_kw(claim) if claim.rating_basis == "mechanical_output" else None
            electrical = Decimal(0)
        elif claim.drive == "electric":
            if claim.rating_basis == "mechanical_output":
                mechanical = _unit_kw(claim)
                if mechanical is not None and claim.efficiency is not None:
                    electrical = mechanical / claim.efficiency
            elif claim.rating_basis == "electrical_input":
                electrical = _unit_kw(claim)
            else:
                electrical = None
    connected = None
    coincident = None
    incremental = None
    energy = None
    average = None
    if not active:
        electrical = Decimal(0)
        connected = Decimal(0)
        coincident = Decimal(0)
        incremental = Decimal(0)
    elif electrical is not None:
        if claim.count is not None:
            if claim.state in ("existing", "installed"):
                connected = electrical * claim.count
                incremental = Decimal(0)
            elif claim.state in ("new", "proposed"):
                connected = electrical * claim.count
            if claim.state in ("new", "proposed"):
                incremental = electrical * claim.count
        if claim.role == "standby":
            coincident = Decimal(0)
        elif claim.operating_count is not None:
            coincident = electrical * claim.operating_count
        if (
            coincident is not None
            and claim.duty_fraction is not None
            and claim.period_hours is not None
        ):
            average = coincident * claim.duty_fraction
            energy = average * claim.period_hours / Decimal(1000)
    known = all(value is not None for value in (electrical, connected, coincident))
    digest = _claim_hash(claim)
    return EquipmentDemandItem(
        equipment_id=_equipment_key(claim.equipment_id),
        mechanical_kw=mechanical,
        electrical_input_kw=electrical,
        connected_kw=connected,
        coincident_kw=coincident,
        incremental_kw=incremental,
        energy_mwh=energy,
        average_kw=average,
        status="known" if known else "unknown",
        input_hash=digest,
    )


def _total(items: Sequence[EquipmentDemandItem], field: str) -> Decimal | None:
    values = [getattr(item, field) for item in items]
    if not values or not all(value is not None for value in values):
        return None
    with localcontext(DEMAND_CONTEXT) as context:
        context.prec = 28
        return sum(values, Decimal(0))


def _equipment_key(value: str) -> str:
    return value.strip().casefold()


def _canonical_value(value: object) -> str:
    if isinstance(value, Decimal):
        sign, raw_digits, exponent = value.as_tuple()
        if not isinstance(exponent, int):
            raise ValueError("cannot canonicalize a nonfinite Decimal")
        digits = list(raw_digits)
        if not digits or not any(digits):
            return "0"
        while digits[-1] == 0:
            digits.pop()
            exponent += 1
        return format(Decimal((sign, tuple(digits), exponent)), "f")
    if isinstance(value, date | datetime):
        return value.isoformat()
    return repr(value)


def _claim_signature(claim: EquipmentClaim) -> tuple[str, ...]:
    return tuple(
        _equipment_key(claim.equipment_id)
        if field.name == "equipment_id"
        else _canonical_value(getattr(claim, field.name))
        for field in fields(EquipmentClaim)
        if field.name not in {"quote", "source_id", "start", "end"}
    )


def _claim_hash(claim: EquipmentClaim) -> str:
    serialized = tuple(
        _canonical_value(getattr(claim, field.name)) for field in fields(EquipmentClaim)
    )
    return sha256(repr(serialized).encode("utf-8")).hexdigest()


def _windows_do_not_overlap(
    items: Sequence[EquipmentDemandItem], claims: Sequence[EquipmentClaim | None]
) -> bool:
    windows = [
        (claim.effective_from or date.min, claim.effective_until or date.max)
        for item, claim in zip(items, claims, strict=True)
        if claim is not None
        and item.electrical_input_kw is not None
        and item.electrical_input_kw > 0
        and item.coincident_kw is not None
        and item.coincident_kw > 0
    ]
    return len(windows) > 1 and max(start for start, _ in windows) > min(end for _, end in windows)


def calculate_equipment_demand(
    claims: Sequence[EquipmentClaim], as_of: date | datetime | None = None
) -> EquipmentDemandResult:
    """Calculate conservative equipment totals; absent required inputs remain unknown."""
    if as_of is not None and not isinstance(as_of, date | datetime):
        raise ValueError("as_of must be a date or datetime")
    frozen_claims = tuple(claims)
    by_id: dict[str, list[EquipmentClaim]] = {}
    for claim in frozen_claims:
        by_id.setdefault(_equipment_key(claim.equipment_id), []).append(claim)
    calculated: list[EquipmentDemandItem] = []
    calculation_claims: list[EquipmentClaim | None] = []
    for equipment_id, rows in sorted(by_id.items()):
        signatures = {_claim_signature(row) for row in rows}
        if len(signatures) == 1:
            canonical_claim = min(rows, key=_claim_hash)
            with localcontext(DEMAND_CONTEXT) as context:
                context.prec = 28
                calculated.append(_item(canonical_claim, as_of))
            calculation_claims.append(canonical_claim)
            continue
        digest = sha256(repr(tuple(sorted(signatures))).encode("utf-8")).hexdigest()
        calculated.append(
            EquipmentDemandItem(
                equipment_id=equipment_id,
                mechanical_kw=None,
                electrical_input_kw=None,
                connected_kw=None,
                coincident_kw=None,
                incremental_kw=None,
                energy_mwh=None,
                average_kw=None,
                status="conflicted",
                input_hash=digest,
            )
        )
        calculation_claims.append(None)
    items = tuple(calculated)
    hashes = tuple(item.input_hash for item in items)
    known_connected = [item.connected_kw for item in items if item.connected_kw is not None]
    if known_connected:
        with localcontext(DEMAND_CONTEXT) as context:
            context.prec = 28
            connected_subtotal = sum(known_connected, Decimal(0))
    else:
        connected_subtotal = None
    coincident_kw = _total(items, "coincident_kw")
    energy_mwh = _total(items, "energy_mwh")
    average_kw = _total(items, "average_kw")
    unresolved: tuple[str, ...] = ()
    if _windows_do_not_overlap(items, calculation_claims):
        coincident_kw = None
        energy_mwh = None
        average_kw = None
        unresolved = ("equipment operating windows do not overlap",)
    return EquipmentDemandResult(
        model_id=MODEL_ID,
        model_version=MODEL_VERSION,
        as_of=as_of,
        inputs=frozen_claims,
        input_hashes=hashes,
        items=items,
        mechanical_kw=_total(items, "mechanical_kw"),
        electrical_input_kw=_total(items, "electrical_input_kw"),
        connected_kw=_total(items, "connected_kw"),
        coincident_kw=coincident_kw,
        incremental_kw=_total(items, "incremental_kw"),
        energy_mwh=energy_mwh,
        average_kw=average_kw,
        known_connected_subtotal_kw=connected_subtotal,
        unresolved=unresolved,
    )
