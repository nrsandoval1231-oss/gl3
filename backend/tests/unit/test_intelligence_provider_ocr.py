import base64
import hashlib
import io

import pytest
from PIL import Image

from gridlens.integrations import intelligence_provider


def _request():
    output = io.BytesIO()
    Image.new("L", (1, 1), 255).save(output, format="PNG", optimize=False, compress_level=9)
    image = output.getvalue()
    return intelligence_provider.ocr_request_payload(
        model="configured-test-model",
        page_images=[
            {
                "source_page": 3,
                "pixel_sha256": hashlib.sha256(image).hexdigest(),
                "image_base64": base64.b64encode(image).decode("ascii"),
            }
        ],
        detail="low",
        max_output_tokens=800,
    )


def test_ocr_responses_request_uses_exact_reviewed_image_and_strict_page_schema():
    request = _request()
    image_input = request["input"][0]["content"][1]
    assert request["model"] == "configured-test-model"
    assert request["store"] is False
    assert request["tools"] == []
    assert request["max_output_tokens"] == 800
    assert request["service_tier"] == "default"
    assert request["prompt_cache_options"] == {"ttl": "30m"}
    assert image_input["type"] == "input_image"
    assert image_input["detail"] == "low"
    assert image_input["image_url"].startswith("data:image/png;base64,")
    assert "input_file" not in str(request) and "application/pdf" not in str(request)
    schema = request["text"]["format"]["schema"]
    assert schema["additionalProperties"] is False
    assert schema["properties"]["pages"]["maxItems"] == 5


def test_token_count_uses_whitelisted_exact_input_without_response_only_fields(monkeypatch):
    request = _request()
    seen = {}

    def post(url, *, headers, payload):
        seen.update(url=url, headers=headers, payload=payload)
        return {"input_tokens": 421, "object": "response.input_tokens"}, "count-id", 1

    monkeypatch.setattr(intelligence_provider, "_post_json", post)
    count = intelligence_provider.call_openai_input_token_count(
        api_key="test-only", model="configured-test-model", response_request=request
    )
    assert count == 421
    assert seen["url"] == "https://api.openai.com/v1/responses/input_tokens"
    assert set(seen["payload"]) == {"model", "instructions", "input", "tools", "text"}
    assert seen["payload"]["input"] == request["input"]
    assert seen["payload"]["text"] == request["text"]
    assert "store" not in seen["payload"]
    assert "max_output_tokens" not in seen["payload"]
    assert "service_tier" not in seen["payload"]
    assert seen["headers"]["Authorization"] == "Bearer test-only"


def test_token_count_rejects_model_mismatch_and_invalid_count(monkeypatch):
    request = _request()
    with pytest.raises(ValueError, match="match its pinned model"):
        intelligence_provider.call_openai_input_token_count(
            api_key="test-only", model="other-model", response_request=request
        )
    monkeypatch.setattr(
        intelligence_provider,
        "_post_json",
        lambda *_args, **_kwargs: ({"input_tokens": True}, None, 1),
    )
    with pytest.raises(intelligence_provider.ProviderResponseError, match="invalid"):
        intelligence_provider.call_openai_input_token_count(
            api_key="test-only", model="configured-test-model", response_request=request
        )
