import base64

import pytest

from gridlens.integrations import intelligence_provider


def _request():
    return intelligence_provider.ocr_request_payload(
        model="configured-test-model",
        pdf_base64=base64.b64encode(b"%PDF-data").decode("ascii"),
        detail="low",
        max_output_tokens=800,
    )


def test_ocr_responses_request_uses_exact_inline_pdf_and_strict_page_schema():
    request = _request()
    file_input = request["input"][0]["content"][1]
    assert request["model"] == "configured-test-model"
    assert request["store"] is False
    assert request["tools"] == []
    assert request["max_output_tokens"] == 800
    assert file_input["type"] == "input_file"
    assert file_input["filename"] == "source.pdf"
    assert file_input["detail"] == "low"
    assert file_input["file_data"] == "data:application/pdf;base64," + base64.b64encode(
        b"%PDF-data"
    ).decode("ascii")
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
