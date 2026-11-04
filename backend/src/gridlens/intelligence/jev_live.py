"""Bounded live authority for TypeSafe Jev decisions (WS2a).

Live Jev may act, but only through closed-vocabulary labels. The structure enforces the
canon's tiers rather than relying on callers:

* acts alone: document routing, event-type and lifecycle labels, materiality, triage;
* acts with corroboration: project matching, only when Jev's probability clears the match
  threshold AND a deterministic key (county, substation, permit number, coordinates) agrees;
  otherwise the effective answer is UNKNOWN;
* never: creating or changing a value, arithmetic, demand amounts. No label field accepts a
  number, quantity or free text, and nothing in this module reads or writes equipment,
  evidence, observation, project or need rows. A live record is a JSON document stored on the
  decision's own ``evidence_judge_runs`` row.

Every authority defaults OFF. Any provider error, timeout, invalid response or over-cap job
produces an abstained record (``fail closed``), never a guess.
"""

from __future__ import annotations

import math
import re
from collections.abc import Mapping
from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Any

from gridlens.intelligence.evidence_judge import (
    Choice,
    DocumentRoute,
    Driver,
    EventType,
    Judgment,
    LifecyclePhase,
    Novelty,
    Side,
)
from gridlens.settings import settings

LIVE_RECORD_VERSION = "jev-live-v1"
PINNED_MODEL = re.compile(r"jev-\d+\.\d+\.\d+")
UNKNOWN = "UNKNOWN"


class Authority(StrEnum):
    ROUTING = "routing"
    LABELS = "labels"
    MATERIALITY = "materiality"
    TRIAGE = "triage"
    MATCHING = "matching"


TIER: dict[Authority, str] = {
    Authority.ROUTING: "alone",
    Authority.LABELS: "alone",
    Authority.MATERIALITY: "alone",
    Authority.TRIAGE: "alone",
    Authority.MATCHING: "corroborated",
}

# The only fields live Jev may write, each with its closed vocabulary. There is deliberately
# no numeric, quantity or free-text field.
AUTHORITY_FIELDS: dict[Authority, dict[str, type[StrEnum]]] = {
    Authority.ROUTING: {"document_route": DocumentRoute},
    Authority.LABELS: {
        "event_type": EventType,
        "lifecycle_phase": LifecyclePhase,
        "driver": Driver,
        "novelty": Novelty,
        "side": Side,
    },
    Authority.MATERIALITY: {"material_change": Choice},
    Authority.TRIAGE: {"new_large_load": Choice, "relevant": Choice},
    Authority.MATCHING: {"same_project": Choice},
}
LABEL_FIELDS = frozenset(name for fields in AUTHORITY_FIELDS.values() for name in fields)
_SETTING = {
    Authority.ROUTING: "jev_live_routing",
    Authority.LABELS: "jev_live_labels",
    Authority.MATERIALITY: "jev_live_materiality",
    Authority.TRIAGE: "jev_live_triage",
    Authority.MATCHING: "jev_live_matching",
}
CORROBORATION_KEYS = ("county", "substation", "permit_number", "coordinates")


def live_authorities() -> tuple[Authority, ...]:
    """Authorities enabled right now; empty unless live mode and the flag are both on."""
    if not (settings.jev_enabled and settings.jev_live_mode):
        return ()
    return tuple(a for a in Authority if getattr(settings, _SETTING[a]))


def live_active() -> bool:
    return bool(live_authorities())


@dataclass(frozen=True)
class LiveLabel:
    """One closed-vocabulary label decision. Construction enforces the authority contract."""

    authority: Authority
    field: str
    jev_value: str
    probability: float
    model: str
    outcome: str  # "accepted" or "abstained"
    reason: str
    corroboration: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        vocabulary = AUTHORITY_FIELDS.get(self.authority, {}).get(self.field)
        if vocabulary is None:
            raise ValueError("field is not a label this authority may write")
        if self.jev_value not in {item.value for item in vocabulary}:
            raise ValueError("label value is outside the closed vocabulary")
        if not (
            isinstance(self.probability, float)
            and math.isfinite(self.probability)
            and 0.0 <= self.probability <= 1.0
        ):
            raise ValueError("probability must be a finite number in [0, 1]")
        if PINNED_MODEL.fullmatch(self.model) is None:
            raise ValueError("a pinned versioned model is required on every decision")
        if self.outcome not in {"accepted", "abstained"}:
            raise ValueError("outcome must be accepted or abstained")
        if self.outcome == "accepted":
            if self.jev_value == UNKNOWN:
                raise ValueError("UNKNOWN can never be accepted")
            if TIER[self.authority] == "corroborated" and not self.corroboration:
                raise ValueError("corroborated authority requires a deterministic key")
            if any(key not in CORROBORATION_KEYS for key in self.corroboration):
                raise ValueError("unknown corroboration key")

    @property
    def effective_value(self) -> str:
        return self.jev_value if self.outcome == "accepted" else UNKNOWN

    def as_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["authority"] = self.authority.value
        data["corroboration"] = list(self.corroboration)
        data["effective_value"] = self.effective_value
        return data


@dataclass(frozen=True)
class Corroboration:
    """Deterministic keys on which the evidence and the candidate project agree."""

    keys: tuple[str, ...] = field(default_factory=tuple)


def _normalized(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(value or "").casefold()).strip()


def _contains_token(passage: str, token: str) -> bool:
    normalized = _normalized(token)
    if len(normalized) < 4:
        return False
    return re.search(rf"\b{re.escape(normalized)}\b", _normalized(passage)) is not None


def _coordinates(facts: Mapping[str, Any]) -> tuple[float, float] | None:
    lat = facts.get("latitude", facts.get("lat"))
    lon = facts.get("longitude", facts.get("lon", facts.get("lng")))
    try:
        pair = (float(lat), float(lon))
    except (TypeError, ValueError):
        return None
    if not all(math.isfinite(v) for v in pair) or not (
        -90 <= pair[0] <= 90 and -180 <= pair[1] <= 180
    ):
        return None
    return pair


def corroborating_keys(
    project_facts: Mapping[str, Any],
    evidence_facts: Mapping[str, Any],
    passage: str = "",
) -> Corroboration:
    """Compare deterministic keys. A missing key on either side never agrees.

    County must match the evidence's own county field (it is never inferred from prose).
    Substation and permit number agree when the evidence field matches or the project's
    value appears verbatim as a whole token in the evidence passage. Coordinates agree when
    both sides carry them and they are within about 1 km.
    """
    agreed: list[str] = []
    county, evidence_county = _normalized(project_facts.get("county")), _normalized(
        evidence_facts.get("county")
    )
    if county and county == evidence_county:
        agreed.append("county")
    for key in ("substation", "permit_number"):
        project_value = project_facts.get(key)
        if not _normalized(project_value):
            continue
        if _normalized(project_value) == _normalized(evidence_facts.get(key)) or (
            _contains_token(passage, str(project_value))
        ):
            agreed.append(key)
    here, there = _coordinates(project_facts), _coordinates(evidence_facts)
    if here and there:
        # 0.01 degrees of latitude is about 1.1 km; compare conservatively with a square.
        if abs(here[0] - there[0]) <= 0.01 and abs(here[1] - there[1]) <= 0.01:
            agreed.append("coordinates")
    return Corroboration(tuple(agreed))


def derive_live_record(
    judgment: Judgment,
    probabilities: Mapping[str, float],
    model: str,
    corroboration: Corroboration | None = None,
) -> dict[str, Any]:
    """Turn one validated judgment into label decisions for the enabled authorities only."""
    abstain_below = settings.jev_abstain_probability
    match_at = settings.jev_match_probability
    labels: list[LiveLabel] = []
    enabled = live_authorities()
    for authority in enabled:
        for name in AUTHORITY_FIELDS[authority]:
            value = str(getattr(judgment, name).value)
            probability = probabilities.get(name)
            if not isinstance(probability, int | float) or isinstance(probability, bool):
                labels.append(
                    LiveLabel(
                        authority, name, UNKNOWN, 0.0, model, "abstained", "PROBABILITY_MISSING"
                    )
                )
                continue
            probability = float(probability)
            keys: tuple[str, ...] = ()
            if value == UNKNOWN:
                outcome, reason = "abstained", "MODEL_ANSWERED_UNKNOWN"
            elif authority is Authority.MATCHING:
                # Only YES can act, and only with a high probability and a deterministic key.
                keys = tuple(corroboration.keys) if corroboration else ()
                if value != Choice.YES.value:
                    outcome, reason = "abstained", "ONLY_YES_CAN_ACT"
                elif probability < match_at:
                    outcome, reason = "abstained", "BELOW_MATCH_PROBABILITY"
                elif not keys:
                    outcome, reason = "abstained", "NO_DETERMINISTIC_KEY_AGREES"
                else:
                    outcome, reason = "accepted", "PROBABILITY_AND_DETERMINISTIC_KEY_AGREE"
            elif probability < abstain_below:
                outcome, reason = "abstained", "BELOW_ABSTAIN_PROBABILITY"
            else:
                outcome, reason = "accepted", "PROBABILITY_AT_OR_ABOVE_THRESHOLD"
            labels.append(
                LiveLabel(
                    authority,
                    name,
                    value,
                    probability,
                    model,
                    outcome,
                    reason,
                    keys if outcome == "accepted" else (),
                )
            )
    return {
        "version": LIVE_RECORD_VERSION,
        "mode": "live",
        "model": model,
        "authorities": [a.value for a in enabled],
        "thresholds": {"abstain": abstain_below, "match": match_at},
        "outcome": "decided",
        "labels": [label.as_dict() for label in labels],
    }


def abstained_record(reason: str, model: str | None = None) -> dict[str, Any]:
    """Fail-closed record: the job is visible, and no label acts."""
    return {
        "version": LIVE_RECORD_VERSION,
        "mode": "live",
        "model": model,
        "authorities": [a.value for a in live_authorities()],
        "outcome": "abstained",
        "reason": reason[:200],
        "labels": [],
    }


def validate_live_record(record: Any) -> dict[str, Any]:
    """Structural guard applied before persistence: label vocabulary only, no values."""
    allowed_top = {
        "version",
        "mode",
        "model",
        "authorities",
        "thresholds",
        "outcome",
        "reason",
        "labels",
    }
    if not isinstance(record, dict) or set(record) - allowed_top:
        raise ValueError("live record has unexpected keys")
    label_keys = {f.name for f in LiveLabel.__dataclass_fields__.values()} | {"effective_value"}
    for item in record.get("labels", []):
        if not isinstance(item, dict) or set(item) - label_keys:
            raise ValueError("live label has unexpected keys")
        if item.get("field") not in LABEL_FIELDS:
            raise ValueError("live label field is not permitted")
    return record


def accepted_labels(result: Mapping[str, Any] | None) -> dict[str, str]:
    """Labels a consumer may act on: accepted, from a pinned model, live record only."""
    live = (result or {}).get("live")
    if not isinstance(live, dict) or live.get("outcome") != "decided":
        return {}
    if PINNED_MODEL.fullmatch(str(live.get("model") or "")) is None:
        return {}
    accepted: dict[str, str] = {}
    for item in live.get("labels", []):
        if item.get("outcome") == "accepted" and item.get("field") in LABEL_FIELDS:
            accepted[item["field"]] = item["jev_value"]
    return accepted
