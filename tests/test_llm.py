import pytest

from src.errors import (
    LLMConfigurationError,
    LLMResponseError,
    LLMServiceError,
)
from src.llm import (
    GeminiProvider,
    build_explanation_prompt,
    build_explanation_request,
    validate_explanation,
)

DECISION_SUMMARY = {
    "summary": {"critical_stockout_items": 2},
    "governance": {
        "data_type": "synthetic",
        "autonomous_action": False,
        "human_review_required": True,
    },
}


class FakeResponse:
    text = (
        "There are CRITICAL and HIGH stockout items. Human review is required."
    )


class FakeModels:
    def __init__(self, response=None, error=None):
        self.calls = 0
        self.response = response or FakeResponse()
        self.error = error

    def generate_content(self, **kwargs):
        self.calls += 1
        if self.error is not None:
            raise self.error
        return self.response


class FakeClient:
    def __init__(self, response=None, error=None):
        self.models = FakeModels(response=response, error=error)


def test_prompt_uses_structured_json_and_delimiters():
    prompt = build_explanation_prompt(DECISION_SUMMARY)

    assert "<analysis_data>" in prompt
    assert "</analysis_data>" in prompt
    assert '"critical_stockout_items": 2' in prompt
    assert "untrusted data" in prompt


def test_explanation_request_preserves_governance_controls():
    request = build_explanation_request(DECISION_SUMMARY)

    assert request["data_type"] == "synthetic"
    assert request["autonomous_action"] is False
    assert request["human_review_required"] is True
    assert request["system_role"] == (
        "health-supply-chain-explanation-assistant"
    )
    assert (
        "Do not recalculate or change any risk classification."
        in (request["prompt"])
    )
    assert (
        "Do not make autonomous operational decisions." in (request["prompt"])
    )


def test_validate_explanation_accepts_compliant_text():
    warnings = validate_explanation(
        "CRITICAL and HIGH items are reported separately. "
        "Human review is required."
    )

    assert warnings == []


def test_validate_explanation_warns_on_missing_sections():
    warnings = validate_explanation("The analysis is complete.")

    assert len(warnings) == 3


def test_provider_requires_api_key(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    with pytest.raises(LLMConfigurationError):
        GeminiProvider(api_key=None)


def test_provider_caches_identical_prompts():
    client = FakeClient()
    provider = GeminiProvider(api_key="test", client=client)

    first = provider.generate_explanation("prompt")
    second = provider.generate_explanation("prompt")

    assert first == second
    assert client.models.calls == 1


def test_provider_refresh_bypasses_cache():
    client = FakeClient()
    provider = GeminiProvider(api_key="test", client=client)

    provider.generate_explanation("prompt")
    provider.generate_explanation("prompt", refresh=True)

    assert client.models.calls == 2


def test_provider_rejects_empty_response():
    response = FakeResponse()
    response.text = ""
    provider = GeminiProvider(
        api_key="test",
        client=FakeClient(response=response),
    )

    with pytest.raises(LLMResponseError):
        provider.generate_explanation("prompt")


def test_provider_wraps_upstream_errors():
    provider = GeminiProvider(
        api_key="test",
        client=FakeClient(error=RuntimeError("boom")),
    )

    with pytest.raises(LLMServiceError):
        provider.generate_explanation("prompt")
