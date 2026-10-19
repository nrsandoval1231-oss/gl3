"""TypeSafe EvidenceJudge adapter; only explicit shadow commands call this provider."""

from __future__ import annotations

import json
import math
import time
from datetime import date, datetime
from typing import Any
from uuid import UUID

from gridlens.integrations.intelligence_provider import call_typesafe
from gridlens.intelligence.evidence_judge import Choice, EventType, InvalidJudgment, Judgment, Level

MODEL = "jev-latest"
SCHEMA_VERSION = "evidence-judge-v1"


def _json_safe(value: Any) -> Any:
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
        return {str(key)[:120]: _json_safe(item) for key, item in list(value.items())[:40]}
    if isinstance(value, list | tuple):
        return [_json_safe(item) for item in value[:8]]
    return str(value)[:1200]


def choice_question(instructions: str, choices: dict[str, str]) -> dict:
    return {
        "type": "choice",
        "instructions": instructions,
        "criteria": choices,
    }


def parse_typesafe_response(
    data: dict, *, expected_model: str = MODEL
) -> tuple[Judgment, str, int | None, int | None]:
    try:
        answers = data["answers"]
        expected = {
            "relevant": Choice,
            "same_project": Choice,
            "event_type": EventType,
            "material_change": Choice,
            "power_relevance": Level,
            "temporary_power_hint": Choice,
            "needs_deep_enrichment": Choice,
        }
        if set(answers) != set(expected):
            raise ValueError("answer keys mismatch")
        raw = {}
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
        return Judgment.model_validate(raw), data["model"], counts[0], counts[1]
    except Exception as exc:
        raise InvalidJudgment("TypeSafe response failed strict EvidenceJudge validation") from exc


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
        request = {
            "model": model,
            "state": {
                "project": {
                    "project_id": state.get("project_id"),
                    "state": state.get("state", {}),
                    "organizations_and_roles": state.get("organizations_and_roles", [])[:8],
                },
                "evidence": {
                    k: str(v)[:1200] if v is not None else None for k, v in evidence.items()
                },
                "candidate_projects": candidates[:8],
            },
            "questions": {
                "relevant": choice_question(
                    "Is this evidence relevant to the physical project's evolving state?",
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
                    "How relevant is the supported event to commercial power investigation?",
                    {v: v for v in ["LOW", "MEDIUM", "HIGH", "UNKNOWN"]},
                ),
                "temporary_power_hint": choice_question(
                    "Does evidence explicitly support temporary or bridge power for this activity?",
                    {"YES": "Explicit hint", "NO": "No hint", "UNKNOWN": "Insufficient"},
                ),
                "needs_deep_enrichment": choice_question(
                    "Would additional bounded research likely resolve material unknowns?",
                    {"YES": "Useful", "NO": "Not useful", "UNKNOWN": "Insufficient"},
                ),
            },
        }
        # State projections contain dates and UUIDs in evidence provenance; normalize
        # before the HTTP boundary so serialization failures cannot masquerade as calls.
        request = _json_safe(request)
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
        judgment, model, input_tokens, output_tokens = parse_typesafe_response(
            data, expected_model=self.model
        )
        return judgment, {
            "model": model,
            "latency_ms": latency_ms,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
        }
