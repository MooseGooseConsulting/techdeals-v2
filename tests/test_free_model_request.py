from __future__ import annotations

import json

import httpx
import pytest

from techdeals.config import OPENROUTER_BASE_URL, Settings
from techdeals.parser import engine
from techdeals.parser.models import RawListingForExtraction


@pytest.mark.asyncio
async def test_configured_free_model_request_omits_unsupported_response_format(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings(
        _env_file=None,
        neon_database_url="postgresql://localhost/test",
        openrouter_api_key="test-openrouter-key",
        kilo_gateway_api="",
        kilo_code_api_key="",
    )
    requests: list[tuple[str, dict]] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append((str(request.url), json.loads(request.content)))
        completion = {
            "id": "chatcmpl-test",
            "object": "chat.completion",
            "created": 1,
            "model": settings.llm_model,
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

    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    real_async_openai = engine.AsyncOpenAI

    def mock_openai_client(**kwargs):
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
        response = await engine.extract_batch([listing])
    finally:
        await http_client.aclose()

    assert response.model == "nvidia/nemotron-3.5-lightning:free"
    assert response.results[0].title == "Test server"
    assert len(requests) == 1
    url, body = requests[0]
    assert url.startswith(OPENROUTER_BASE_URL)
    assert body["model"] == "nvidia/nemotron-3.5-lightning:free"
    assert "response_format" not in body
    assert "json_schema" in body["messages"][0]["content"]
