from __future__ import annotations

import json

import httpx
import pytest
from pydantic import ValidationError

from techdeals.config import (
    AUTHORIZED_LLM_MODEL,
    OPENROUTER_BASE_URL,
    Settings,
)
from techdeals.parser import engine
from techdeals.parser.models import RawListingForExtraction

NON_AUTHORIZED_MODELS = [
    "google/gemini-2.5-flash",
    "openai/gpt-4.1-mini",
    "openrouter/auto",
    "deepseek/deepseek-chat-v3:free",
    "nvidia/nemotron-3.5-lightning",
]


@pytest.fixture
def settings() -> Settings:
    return Settings(
        _env_file=None,
        neon_database_url="postgresql://localhost/test",
        openrouter_api_key="test-openrouter-key",
        kilo_gateway_api="https://paid-or-fallback.example.test/v1",
        kilo_code_api_key="test-kilo-key",
    )


def test_default_model_is_the_one_authorized_free_endpoint() -> None:
    settings = Settings(_env_file=None, neon_database_url="postgresql://localhost/test")
    assert settings.llm_model == AUTHORIZED_LLM_MODEL
    assert AUTHORIZED_LLM_MODEL == "nvidia/nemotron-3.5-lightning:free"


@pytest.mark.parametrize("model", NON_AUTHORIZED_MODELS)
def test_paid_auto_and_other_free_models_are_rejected_from_environment(
    monkeypatch: pytest.MonkeyPatch, tmp_path, model: str
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("NEON_DATABASE_URL", "postgresql://localhost/test")
    monkeypatch.setenv("LLM_MODEL", model)

    with pytest.raises(ValidationError, match="LLM_MODEL must be"):
        Settings()


def test_legacy_kilo_settings_cannot_change_route_or_credentials(settings: Settings) -> None:
    assert settings.llm_base_url == OPENROUTER_BASE_URL
    assert settings.llm_api_key == "test-openrouter-key"


@pytest.mark.asyncio
@pytest.mark.parametrize("model", NON_AUTHORIZED_MODELS)
async def test_explicit_non_authorized_model_fails_before_sdk_construction(
    monkeypatch: pytest.MonkeyPatch, settings: Settings, model: str
) -> None:
    monkeypatch.setattr(engine, "get_settings", lambda: settings)
    sdk_calls = []

    def forbidden_sdk_call(**kwargs):
        sdk_calls.append(kwargs)
        raise AssertionError("unauthorized model reached SDK construction")

    monkeypatch.setattr(engine, "AsyncOpenAI", forbidden_sdk_call)
    listing = RawListingForExtraction(
        capture_id="listing-1",
        source="test",
        url="https://example.test/listing-1",
        title="Test server",
        raw_text="Test server for sale",
        payload_format="text",
    )

    with pytest.raises(ValueError, match="LLM_MODEL must be"):
        await engine.extract_batch([listing], model=model)
    assert sdk_calls == []


@pytest.mark.asyncio
async def test_authorized_model_uses_openrouter_and_prompt_schema_without_response_format(
    monkeypatch: pytest.MonkeyPatch, settings: Settings
) -> None:
    requests: list[tuple[str, dict]] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append((str(request.url), json.loads(request.content)))
        completion = {
            "id": "chatcmpl-test",
            "object": "chat.completion",
            "created": 1,
            "model": AUTHORIZED_LLM_MODEL,
            "choices": [{
                "index": 0,
                "finish_reason": "stop",
                "message": {
                    "role": "assistant",
                    "content": json.dumps({
                        "results": [{"title": "Test server", "parse_confidence": 0.9}]
                    }),
                },
            }],
            "usage": {"prompt_tokens": 10, "completion_tokens": 10, "total_tokens": 20},
        }
        return httpx.Response(200, json=completion)

    transport = httpx.MockTransport(handler)
    http_client = httpx.AsyncClient(transport=transport)
    real_async_openai = engine.AsyncOpenAI
    client_kwargs: dict = {}

    def mock_openai_client(**kwargs):
        client_kwargs.update(kwargs)
        return real_async_openai(**kwargs, http_client=http_client)

    monkeypatch.setattr(engine, "get_settings", lambda: settings)
    monkeypatch.setattr(engine, "AsyncOpenAI", mock_openai_client)
    listing = RawListingForExtraction(
        capture_id="listing-1",
        source="test",
        url="https://example.test/listing-1",
        title="Test server",
        raw_text="Test server for sale",
        payload_format="text",
    )

    try:
        response = await engine.extract_batch([listing], model=AUTHORIZED_LLM_MODEL)
    finally:
        await http_client.aclose()

    assert response.model == AUTHORIZED_LLM_MODEL
    assert response.results[0].title == "Test server"
    assert client_kwargs == {
        "base_url": OPENROUTER_BASE_URL,
        "api_key": "test-openrouter-key",
    }
    assert len(requests) == 1
    url, body = requests[0]
    assert url.startswith(OPENROUTER_BASE_URL)
    assert body["model"] == AUTHORIZED_LLM_MODEL
    assert "response_format" not in body
    assert "json_schema" in body["messages"][0]["content"]
