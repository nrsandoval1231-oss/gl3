"""No-fallback bounded transport for advisory TypeSafe and OpenAI Responses calls."""

from __future__ import annotations

import json
import time
from typing import Any

import httpx

TIMEOUT_SECONDS = 45
MAX_RESPONSE_BYTES = 65_536


class ProviderResponseError(RuntimeError):
    def __init__(self, message: str, *, request_id: str | None = None, conclusive: bool = False):
        super().__init__(message)
        self.request_id = request_id
        self.conclusive = conclusive


def _post_json(
    url: str, *, headers: dict[str, str], payload: dict[str, Any]
) -> tuple[dict[str, Any], str | None, int]:
    started = time.monotonic()
    request_id = None
    try:
        with httpx.Client(timeout=TIMEOUT_SECONDS) as client:
            with client.stream("POST", url, headers=headers, json=payload) as response:
                request_id = response.headers.get("x-request-id")
                if response.status_code >= 400:
                    raise ProviderResponseError(
                        f"Provider returned HTTP {response.status_code}",
                        request_id=request_id,
                        conclusive=response.status_code < 500,
                    )
                length = response.headers.get("content-length")
                if length and int(length) > MAX_RESPONSE_BYTES:
                    raise ProviderResponseError(
                        "Provider response exceeds byte limit", request_id=request_id
                    )
                body = bytearray()
                for chunk in response.iter_bytes():
                    body.extend(chunk)
                    if len(body) > MAX_RESPONSE_BYTES:
                        raise ProviderResponseError(
                            "Provider response exceeds byte limit", request_id=request_id
                        )
        data = json.loads(body)
        if not isinstance(data, dict):
            raise ProviderResponseError(
                "Provider response must be a JSON object", request_id=request_id, conclusive=True
            )
        request_id = request_id or (data.get("id") if isinstance(data.get("id"), str) else None)
        return data, request_id, int((time.monotonic() - started) * 1000)
    except ProviderResponseError:
        raise
    except (httpx.TimeoutException, httpx.TransportError) as exc:
        raise ProviderResponseError(type(exc).__name__) from exc
    except (ValueError, json.JSONDecodeError) as exc:
        raise ProviderResponseError(
            "Provider response was invalid JSON", request_id=request_id, conclusive=True
        ) from exc


def call_typesafe(*, api_key: str, model: str, payload: dict[str, Any]) -> dict[str, Any]:
    if not api_key or not model:
        raise ValueError("TypeSafe credentials and pinned model are required")
    request = {"model": model, **payload}
    data, request_id, latency_ms = _post_json(
        "https://api.typesafe.ai/v1/systemone",
        headers={"Authorization": f"Bearer {api_key}"},
        payload=request,
    )
    data["provider_response_id"] = request_id
    data["provider_latency_ms"] = latency_ms
    return data


def call_openai(
    *,
    api_key: str,
    model: str,
    instructions: str,
    input_payload: dict[str, Any],
    max_output_tokens: int,
) -> dict[str, Any]:
    if not api_key or not model:
        raise ValueError("OpenAI credentials and pinned model are required")
    data, request_id, latency_ms = _post_json(
        "https://api.openai.com/v1/responses",
        headers={"Authorization": f"Bearer {api_key}"},
        payload={
            "model": model,
            "instructions": instructions,
            "input": json.dumps(input_payload, ensure_ascii=True, separators=(",", ":")),
            "store": False,
            "tools": [],
            "max_output_tokens": max_output_tokens,
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": "grounded_candidates",
                    "strict": True,
                    "schema": _grounded_schema(),
                }
            },
        },
    )
    if data.get("status") != "completed":
        raise ProviderResponseError(
            f"OpenAI response status {data.get('status', 'missing')}",
            request_id=request_id,
            conclusive=True,
        )
    if not isinstance(data.get("output"), list):
        raise ProviderResponseError(
            "OpenAI Responses output is missing", request_id=request_id, conclusive=True
        )
    if any(
        isinstance(item, dict)
        and any(
            isinstance(part, dict) and part.get("type") == "refusal"
            for part in item.get("content", [])
        )
        for item in data["output"]
    ):
        raise ProviderResponseError(
            "OpenAI refused the request", request_id=request_id, conclusive=True
        )
    parts = [
        item.get("text", "")
        for block in data["output"]
        if isinstance(block, dict)
        for item in block.get("content", [])
        if isinstance(item, dict) and item.get("type") == "output_text"
    ]
    try:
        output = json.loads("".join(parts))
    except json.JSONDecodeError as exc:
        raise ProviderResponseError(
            "OpenAI structured output was invalid JSON", request_id=request_id, conclusive=True
        ) from exc
    usage = data.get("usage") or {}
    return {
        "model": data.get("model"),
        "provider_response_id": request_id,
        "latency_ms": latency_ms,
        "output": output,
        "input_tokens": usage.get("input_tokens"),
        "output_tokens": usage.get("output_tokens"),
    }


def _grounded_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "candidates",
            "hypotheses",
            "contradictions",
            "unresolved_questions",
            "candidate_orgs",
            "proposed_queries",
            "suggested_pursuit",
        ],
        "properties": {
            "candidates": {
                "type": "array",
                "maxItems": 20,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": [
                        "field",
                        "value",
                        "unit",
                        "evidence_id",
                        "evidence_hash",
                        "quote",
                        "section",
                        "page",
                        "span_start",
                        "span_end",
                        "publisher",
                        "published_date",
                        "support",
                        "status",
                    ],
                    "properties": {
                        "field": {
                            "type": "string",
                            "enum": [
                                "utility_online_date",
                                "temporary_load_mw",
                                "construction_start",
                                "commissioning_window",
                                "natural_gas_availability",
                                "direct_buyer_authority",
                            ],
                        },
                        "value": {"type": "string"},
                        "unit": {"type": ["string", "null"]},
                        "evidence_id": {"type": "string"},
                        "evidence_hash": {"type": "string"},
                        "quote": {"type": "string"},
                        "section": {"type": "string", "enum": ["title", "abstract"]},
                        "page": {"type": ["integer", "null"], "minimum": 1},
                        "span_start": {"type": "integer"},
                        "span_end": {"type": "integer"},
                        "publisher": {"type": "string"},
                        "published_date": {"type": ["string", "null"]},
                        "support": {"type": "string", "enum": ["direct", "inferred", "ambiguous"]},
                        "status": {"type": "string", "enum": ["candidate"]},
                    },
                },
            },
            "hypotheses": {"type": "array", "maxItems": 8, "items": {"type": "string"}},
            "contradictions": {"type": "array", "maxItems": 8, "items": {"type": "string"}},
            "unresolved_questions": {"type": "array", "maxItems": 12, "items": {"type": "string"}},
            "candidate_orgs": {"type": "array", "maxItems": 8, "items": {"type": "string"}},
            "proposed_queries": {"type": "array", "maxItems": 8, "items": {"type": "string"}},
            "suggested_pursuit": {
                "type": ["object", "null"],
                "additionalProperties": False,
                "required": ["title", "rationale"],
                "properties": {"title": {"type": "string"}, "rationale": {"type": "string"}},
            },
        },
    }
