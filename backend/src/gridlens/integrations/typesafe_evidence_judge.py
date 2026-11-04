"""TypeSafe EvidenceJudge adapter.

Questions are about electrical demand: electric versus combustion driver in the quoted
passage, new versus existing equipment, demand versus supply, lifecycle phase, and whether
the filing describes a new large load. Every answer is a closed-vocabulary label with a
probability. The adapter never asks for, and the parser never accepts, a quantity or value.

Backward compatibility: results stored by the earlier question set carry
``temporary_power_hint`` and lack the demand labels. ``Judgment`` still validates those
rows (new labels default to UNKNOWN); the retired question is simply no longer asked.
"""

from __future__ import annotations

import json
import math
import time
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any
from uuid import UUID

from gridlens.integrations.intelligence_provider import call_typesafe
from gridlens.intelligence.evidence_judge import (
    Choice,
    DocumentRoute,
    Driver,
    EventType,
    InvalidJudgment,
    Judgment,
    Level,
    LifecyclePhase,
    Novelty,
    Side,
)
from gridlens.intelligence.jev_passages import bound_passage, passage_budget_bytes, request_bytes

# Pinned, versioned model; `jev-latest` is never used. Runtime value comes from settings.
MODEL = "jev-1.13.0"
SCHEMA_VERSION = "evidence-judge-v2"
LEGACY_SCHEMA_VERSIONS = ("evidence-judge-v1",)
PASSAGE_KEYS = ("abstract", "passage", "text")

# Closed answer vocabulary per question. Order is the request order.
ANSWER_ENUMS: dict[str, Any] = {
    "relevant": Choice,
    "same_project": Choice,
    "event_type": EventType,
    "material_change": Choice,
    "power_relevance": Level,
    "needs_deep_enrichment": Choice,
    "driver": Driver,
    "novelty": Novelty,
    "side": Side,
    "lifecycle_phase": LifecyclePhase,
    "new_large_load": Choice,
    "document_route": DocumentRoute,
}


def _json_safe(value: Any, limit: int = 1200) -> Any:
    """Convert projected SQLAlchemy/Pydantic values to bounded JSON primitives."""
    if value is None or isinstance(value, str | bool | int):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, datetime | date):
        return value.isoformat()
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, dict):
        return {str(key)[:120]: _json_safe(item, limit) for key, item in list(value.items())[:40]}
    if isinstance(value, list | tuple):
        return [_json_safe(item, limit) for item in value[:8]]
    return str(value)[:limit]


def choice_question(instructions: str, choices: dict[str, str]) -> dict:
    return {
        "type": "choice",
        "instructions": instructions,
        "criteria": choices,
    }


@dataclass(frozen=True)
class ParsedAnswers:
    """Validated labels plus the probability Jev assigned to each chosen label."""

    judgment: Judgment
    probabilities: dict[str, float]
    model: str
    input_tokens: int | None
    output_tokens: int | None


def parse_typesafe_answers(data: dict, *, expected_model: str = MODEL) -> ParsedAnswers:
    try:
        answers = data["answers"]
        expected = ANSWER_ENUMS
        if set(answers) != set(expected):
            raise ValueError("answer keys mismatch")
        raw = {}
        chosen_probability: dict[str, float] = {}
        for name, enum in expected.items():
            answer = answers[name]
            enum(answer.get("choice"))
            confidence = answer.get("confidence")
            if (
                answer.get("type") != "choice"
                or not isinstance(confidence, int | float)
                or isinstance(confidence, bool)
                or not math.isfinite(confidence)
                or not 0 <= confidence <= 1
            ):
                raise ValueError("invalid choice answer")
            probabilities = answer.get("probabilities")
            if not isinstance(probabilities, dict) or not probabilities:
                raise ValueError("choice probabilities are required")
            probability_values = list(probabilities.values())
            if (
                not set(probabilities).issubset({item.value for item in enum})
                or answer["choice"] not in probabilities
                or any(
                    not isinstance(value, int | float)
                    or isinstance(value, bool)
                    or not math.isfinite(value)
                    or not 0 <= value <= 1
                    for value in probability_values
                )
                or not 0.98 <= sum(probability_values) <= 1.02
            ):
                raise ValueError("invalid choice probability distribution")
            raw[name] = answer["choice"]
            chosen_probability[name] = float(probabilities[answer["choice"]])
        usage_value = data.get("usage")
        if not isinstance(data.get("model"), str) or not data["model"]:
            raise ValueError("missing model")
        if data["model"] != expected_model:
            raise ValueError("unexpected model")
        if usage_value is not None and not isinstance(usage_value, dict):
            raise ValueError("invalid usage")
        usage = usage_value if isinstance(usage_value, dict) else {}
        counts = []
        for key in ("input_tokens", "output_tokens"):
            count = usage.get(key)
            if count is not None and (
                not isinstance(count, int) or isinstance(count, bool) or count < 0
            ):
                raise ValueError("invalid usage")
            counts.append(count)
        return ParsedAnswers(
            Judgment.model_validate(raw), chosen_probability, data["model"], counts[0], counts[1]
        )
    except Exception as exc:
        raise InvalidJudgment("TypeSafe response failed strict EvidenceJudge validation") from exc


def parse_typesafe_response(
    data: dict, *, expected_model: str = MODEL
) -> tuple[Judgment, str, int | None, int | None]:
    parsed = parse_typesafe_answers(data, expected_model=expected_model)
    return parsed.judgment, parsed.model, parsed.input_tokens, parsed.output_tokens


QUESTIONS: dict[str, dict] = {
    "relevant": choice_question(
        "Does this passage describe electrical demand, on-site power equipment, or a facility "
        "that would create electrical demand at the physical project?",
        {"YES": "Relevant", "NO": "Irrelevant", "UNKNOWN": "Insufficient"},
    ),
    "same_project": choice_question(
        "Does this evidence refer to the selected exact physical project?",
        {"YES": "Explicitly same", "NO": "Different", "UNKNOWN": "Ambiguous"},
    ),
    "event_type": choice_question(
        "Classify the supported event.",
        {
            v: v
            for v in [
                "construction",
                "electrical_construction",
                "commissioning",
                "utility",
                "procurement",
                "buyer",
                "other",
                "UNKNOWN",
            ]
        },
    ),
    "material_change": choice_question(
        "Does the retained evidence support a material accepted-state change?",
        {"YES": "Material", "NO": "Not material", "UNKNOWN": "Insufficient"},
    ),
    "power_relevance": choice_question(
        "How strongly does the passage evidence new or expanded electrical demand?",
        {v: v for v in ["LOW", "MEDIUM", "HIGH", "UNKNOWN"]},
    ),
    "needs_deep_enrichment": choice_question(
        "Would additional bounded research likely resolve material unknowns?",
        {"YES": "Useful", "NO": "Not useful", "UNKNOWN": "Insufficient"},
    ),
    "driver": choice_question(
        "In the quoted passage, is the described equipment or load driven electrically "
        "(motors, electric heat, grid-connected load) or by combustion (engines, turbines, "
        "generators, fired heaters)? Answer only from the passage; do not infer a quantity.",
        {
            "ELECTRIC": "Electrically driven",
            "COMBUSTION": "Combustion driven",
            "BOTH": "Both are described",
            "UNKNOWN": "Insufficient",
        },
    ),
    "novelty": choice_question(
        "Does the passage describe new or added equipment or load, or existing equipment "
        "that is already in service, being replaced like for like, or on standby?",
        {"NEW": "New or added", "EXISTING": "Existing", "UNKNOWN": "Insufficient"},
    ),
    "side": choice_question(
        "Does the passage describe electrical demand (a load that consumes power) or "
        "supply (generation, interconnection capacity or utility infrastructure that "
        "provides power)?",
        {"DEMAND": "Demand", "SUPPLY": "Supply", "UNKNOWN": "Insufficient"},
    ),
    "lifecycle_phase": choice_question(
        "What lifecycle phase does the passage evidence for the described facility or "
        "equipment?",
        {
            "planned": "Announced or planned",
            "permitted": "Permit or approval issued or pending",
            "under_construction": "Under construction",
            "commissioning": "Commissioning or startup",
            "operating": "Operating",
            "cancelled": "Cancelled, withdrawn or denied",
            "UNKNOWN": "Insufficient",
        },
    ),
    "new_large_load": choice_question(
        "Does this filing or passage describe a new large electrical load, such as a data "
        "center, industrial plant or large processing facility, rather than an incidental "
        "or existing load?",
        {"YES": "New large load", "NO": "Not a new large load", "UNKNOWN": "Insufficient"},
    ),
    "document_route": choice_question(
        "What is the best route for this document or page? table: tabular equipment or "
        "load data; narrative: prose describing equipment, load or lifecycle; scan: image "
        "of text with no usable text layer; irrelevant: no electrical-demand content.",
        {
            "table": "Tabular data",
            "narrative": "Narrative prose",
            "scan": "Scanned image",
            "irrelevant": "Irrelevant",
            "UNKNOWN": "Insufficient",
        },
    ),
}


class TypesafeEvidenceJudge:
    def __init__(
        self,
        api_key: str,
        *,
        model: str = MODEL,
        timeout: float = 12.0,
        caller: Any | None = None,
    ):
        self.api_key, self.model, self.timeout, self.caller = api_key, model, timeout, caller

    @staticmethod
    def build_request(
        state: dict, evidence: dict, candidates: list[dict], *, model: str = MODEL
    ) -> dict:
        def assemble(evidence_value: dict) -> dict:
            # State projections contain dates and UUIDs in evidence provenance; normalize
            # before the HTTP boundary so serialization failures cannot masquerade as calls.
            return _json_safe(
                {
                    "model": model,
                    "state": {
                        "project": {
                            "project_id": state.get("project_id"),
                            "state": state.get("state", {}),
                            "organizations_and_roles": state.get("organizations_and_roles", [])[
                                :8
                            ],
                        },
                        "evidence": evidence_value,
                        "candidate_projects": candidates[:8],
                    },
                    "questions": QUESTIONS,
                }
            )

        # Measure the request without passage text, then give the passage the remaining
        # budget under the verified total-input ceiling instead of a fixed 1,200-char cut.
        stripped = {
            k: (None if k in PASSAGE_KEYS else (str(v)[:1200] if v is not None else None))
            for k, v in evidence.items()
        }
        budget = passage_budget_bytes(request_bytes(assemble(stripped)))
        evidence_value: dict[str, Any] = {}
        passage_meta: dict[str, Any] = {}
        for key, value in evidence.items():
            if key in PASSAGE_KEYS and value is not None:
                evidence_value[key], passage_meta[key] = bound_passage(str(value), budget)
                budget = max(0, budget - len(evidence_value[key].encode("utf-8")))
            else:
                evidence_value[key] = str(value)[:1200] if value is not None else None
        if passage_meta:
            evidence_value["passage_bounds"] = passage_meta
        request = assemble(evidence_value)
        json.dumps(request, allow_nan=False)
        return request

    def judge(self, state: dict, evidence: dict, candidates: list[dict]) -> tuple[Judgment, dict]:
        request = self.build_request(state, evidence, candidates, model=self.model)
        started = time.monotonic()
        if self.caller is None:
            data = call_typesafe(
                api_key=self.api_key,
                model=self.model,
                payload={key: value for key, value in request.items() if key != "model"},
                timeout_seconds=self.timeout,
            )
            latency_ms = data.get("provider_latency_ms", int((time.monotonic() - started) * 1000))
        else:
            response = self.caller(
                "https://api.typesafe.ai/v1/systemone",
                headers={"Authorization": f"Bearer {self.api_key}"},
                json=request,
                timeout=self.timeout,
            )
            response.raise_for_status()
            data = response.json()
            latency_ms = int((time.monotonic() - started) * 1000)
        parsed = parse_typesafe_answers(data, expected_model=self.model)
        return parsed.judgment, {
            "model": parsed.model,
            "latency_ms": latency_ms,
            "input_tokens": parsed.input_tokens,
            "output_tokens": parsed.output_tokens,
            "probabilities": parsed.probabilities,
            "passage_bounds": request["state"]["evidence"].get("passage_bounds", {}),
        }
