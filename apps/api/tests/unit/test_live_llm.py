"""Unit tests for live LLM providers and OpenAI-compatible adapter (Contract C08)."""

import json
import pytest
import httpx
from unittest.mock import patch

from querylens.config import Settings
from querylens.llm.live import OpenAICompatibleProvider, LiveLLMError, get_live_llm_provider
from querylens.llm.protocol import GeneratedCandidate


def test_provider_presets():
    """Verify Groq, OpenRouter, and OpenAI default configurations."""
    # Groq preset
    s_groq = Settings(_env_file=None, llm_provider="groq", llm_api_key="gsk_test")
    base, model, key = s_groq.get_effective_llm_config()
    assert base == "https://api.groq.com/openai/v1"
    assert model == "openai/gpt-oss-120b"
    assert key == "gsk_test"

    # OpenRouter preset
    s_or = Settings(_env_file=None, llm_provider="openrouter", llm_api_key="sk-or-test")
    base, model, key = s_or.get_effective_llm_config()
    assert base == "https://openrouter.ai/api/v1"
    assert model == "meta-llama/llama-3.3-70b-instruct:free"

    # Custom override
    s_custom = Settings(
        _env_file=None,
        llm_provider="groq",
        llm_model="custom-model",
        llm_api_base="https://custom.api/v1",
        llm_api_key="key",
    )
    base, model, key = s_custom.get_effective_llm_config()
    assert base == "https://custom.api/v1"
    assert model == "custom-model"


@pytest.mark.asyncio
async def test_openai_compatible_provider_success():
    """Verify successful generation of SQL candidate and token usage."""
    provider = OpenAICompatibleProvider(
        api_base="https://api.groq.com/openai/v1",
        model="llama-3.3-70b-versatile",
        api_key="gsk_test",
    )

    mock_resp_data = {
        "choices": [
            {
                "message": {
                    "content": json.dumps(
                        {
                            "sql": "SELECT id, name FROM customers LIMIT 10;",
                            "assumptions": ["Limited to 10 customers"],
                            "requires_clarification": False,
                            "clarification_question": None,
                        }
                    )
                }
            }
        ],
        "usage": {
            "prompt_tokens": 120,
            "completion_tokens": 25,
        },
    }

    mock_response = httpx.Response(200, json=mock_resp_data)

    client = httpx.AsyncClient(transport=httpx.MockTransport(lambda request: mock_response))
    with patch("querylens.llm.live.httpx.AsyncClient", return_value=client):
        candidate = await provider.generate(
            question="list 10 customers",
            dialect="postgresql",
            schema_context="CREATE TABLE customers (id INT, name TEXT);",
        )

        assert isinstance(candidate, GeneratedCandidate)
        assert candidate.sql == "SELECT id, name FROM customers LIMIT 10;"
        assert candidate.assumptions == ["Limited to 10 customers"]
        assert candidate.requires_clarification is False
        assert candidate.usage.prompt_tokens == 120
        assert candidate.usage.completion_tokens == 25


@pytest.mark.asyncio
async def test_openai_compatible_provider_clarification():
    """Verify model returning clarification_required."""
    provider = OpenAICompatibleProvider(
        api_base="https://api.groq.com/openai/v1",
        model="llama-3.3-70b-versatile",
        api_key="gsk_test",
    )

    mock_resp_data = {
        "choices": [
            {
                "message": {
                    "content": json.dumps(
                        {
                            "sql": None,
                            "assumptions": [],
                            "requires_clarification": True,
                            "clarification_question": "Which year are you referring to?",
                        }
                    )
                }
            }
        ],
        "usage": {"prompt_tokens": 80, "completion_tokens": 15},
    }

    mock_response = httpx.Response(200, json=mock_resp_data)

    client = httpx.AsyncClient(transport=httpx.MockTransport(lambda request: mock_response))
    with patch("querylens.llm.live.httpx.AsyncClient", return_value=client):
        candidate = await provider.generate(
            question="show sales",
            dialect="postgresql",
            schema_context="CREATE TABLE sales (id INT);",
        )

        assert candidate.requires_clarification is True
        assert candidate.clarification_question == "Which year are you referring to?"
        assert candidate.sql is None


@pytest.mark.asyncio
async def test_openai_compatible_markdown_stripping():
    """Verify markdown code fences ```json ... ``` are cleanly parsed."""
    provider = OpenAICompatibleProvider(
        api_base="https://api.groq.com/openai/v1",
        model="llama-3.3-70b-versatile",
        api_key="gsk_test",
    )

    raw_markdown = '```json\n{"sql": "SELECT 1;", "assumptions": [], "requires_clarification": false}\n```'
    mock_resp_data = {
        "choices": [{"message": {"content": raw_markdown}}],
        "usage": {"prompt_tokens": 50, "completion_tokens": 10},
    }

    mock_response = httpx.Response(200, json=mock_resp_data)

    client = httpx.AsyncClient(transport=httpx.MockTransport(lambda request: mock_response))
    with patch("querylens.llm.live.httpx.AsyncClient", return_value=client):
        candidate = await provider.generate(
            question="ping",
            dialect="mysql",
            schema_context="",
        )
        assert candidate.sql == "SELECT 1;"


@pytest.mark.asyncio
async def test_openai_compatible_error_handling():
    """Verify HTTP errors raise LiveLLMError."""
    provider = OpenAICompatibleProvider(
        api_base="https://api.groq.com/openai/v1",
        model="llama-3.3-70b-versatile",
        api_key="gsk_test",
    )

    mock_response = httpx.Response(401, text="Invalid API Key")

    client = httpx.AsyncClient(transport=httpx.MockTransport(lambda request: mock_response))
    with patch("querylens.llm.live.httpx.AsyncClient", return_value=client):
        with pytest.raises(LiveLLMError) as exc_info:
            await provider.generate(
                question="ping",
                dialect="postgresql",
                schema_context="",
            )
        assert exc_info.value.code == "MODEL_UNAVAILABLE"
