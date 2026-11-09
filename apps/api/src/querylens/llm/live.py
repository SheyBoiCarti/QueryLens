"""OpenAI-compatible live LLM provider for Groq, OpenRouter, and OpenAI (Contracts C01, C08)."""

from __future__ import annotations

import asyncio
import json
import re
import time
from typing import Any
import httpx

from querylens.config import Settings, get_settings
from querylens.llm.protocol import GeneratedCandidate, LLMUsage
from querylens.llm.provider import LLMProvider
from querylens.pipeline.context import estimate_tokens


class LiveLLMError(Exception):
    """Base exception for live LLM provider failures."""

    def __init__(self, message: str, code: str = "MODEL_OUTPUT_INVALID") -> None:
        super().__init__(message)
        self.code = code


class OpenAICompatibleProvider(LLMProvider):
    """Universal OpenAI-compatible chat completions provider for Groq, OpenRouter, and OpenAI."""

    def __init__(
        self,
        api_base: str,
        model: str,
        api_key: str,
        max_response_bytes: int = 65536,
    ) -> None:
        self.api_base = api_base.rstrip("/")
        self.model = model
        self.api_key = api_key
        self.max_response_bytes = max_response_bytes

    def _build_system_prompt(self, dialect: str) -> str:
        return (
            f"You are QueryLens, an enterprise natural-language analytics engine generating secure, read-only SQL for {dialect}.\n"
            "Rules:\n"
            "1. Only generate read-only SELECT queries. Strictly never generate DML, DDL, transaction control, or locking statements.\n"
            f"2. Use strictly compliant {dialect} syntax and functions.\n"
            "3. ONLY use tables and columns explicitly defined in the provided schema context. NEVER invent or assume columns (e.g. do NOT assume total_amount on orders if orders only has id, customer_id, order_date, status; check line_items or payments instead).\n"
            "4. Output MUST be a single valid JSON object with these exact keys:\n"
            '   - "sql": string or null (the SQL query, terminated with a semicolon)\n'
            '   - "assumptions": array of strings (business assumptions or filters applied, max 10 items, max 500 chars each)\n'
            '   - "requires_clarification": boolean\n'
            '   - "clarification_question": string or null (required if requires_clarification is true, max 500 chars)\n'
            "5. If repairing a previous failed query, carefully fix the exact error reported and DO NOT repeat the same SQL.\n"
            "6. Do NOT include Markdown code blocks or any other text outside the JSON object."
        )

    def _clean_json_text(self, text: str) -> str:
        """Strip markdown fences if the model returned them."""
        stripped = text.strip()
        if stripped.startswith("```"):
            stripped = re.sub(r"^```(?:json)?\s*", "", stripped)
            stripped = re.sub(r"\s*```$", "", stripped)
        return stripped.strip()

    async def generate(
        self,
        question: str,
        dialect: str,
        schema_context: str,
        timeout_sec: float = 15.0,
    ) -> GeneratedCandidate:
        url = f"{self.api_base}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        user_content = (
            f"Database Dialect: {dialect}\n\nSchema Context:\n{schema_context}\n\nUser Question:\n{question}\n"
        )

        settings = get_settings()
        system_prompt = self._build_system_prompt(dialect)
        if estimate_tokens(system_prompt + user_content) + 64 > settings.max_input_tokens:
            raise LiveLLMError("Input exceeds configured token bound", code="TOKEN_BUDGET_EXCEEDED")
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content},
            ],
            "temperature": 0.0,
            "max_tokens": settings.max_output_tokens,
            "response_format": {"type": "json_object"},
        }

        start_time = time.monotonic()
        try:
            async with asyncio.timeout(timeout_sec):
                async with httpx.AsyncClient(timeout=timeout_sec) as client:
                    async with client.stream("POST", url, json=payload, headers=headers) as resp:
                        if resp.status_code != 200:
                            raise LiveLLMError("LLM provider unavailable", code="MODEL_UNAVAILABLE")
                        chunks = bytearray()
                        async for chunk in resp.aiter_bytes():
                            if len(chunks) + len(chunk) > self.max_response_bytes:
                                raise LiveLLMError("LLM response exceeds byte bound")
                            chunks.extend(chunk)
        except (httpx.TimeoutException, TimeoutError) as exc:
            raise LiveLLMError("LLM request timed out", code="DEADLINE_EXCEEDED") from exc
        except LiveLLMError:
            raise
        except httpx.HTTPError as exc:
            raise LiveLLMError("LLM connection unavailable", code="MODEL_UNAVAILABLE") from exc
        latency_ms = int((time.monotonic() - start_time) * 1000)

        try:
            body = json.loads(chunks)
            choice = body["choices"][0]["message"]["content"]
            usage_data = body.get("usage", {})
        except (KeyError, IndexError, TypeError, json.JSONDecodeError) as e:
            raise LiveLLMError(f"Malformed LLM response structure: {e}", code="MODEL_OUTPUT_INVALID") from e

        if not isinstance(choice, str):
            raise LiveLLMError("Model content must be a string")
        cleaned = self._clean_json_text(choice)
        try:
            parsed = json.loads(cleaned)
        except json.JSONDecodeError as e:
            raise LiveLLMError(f"Model did not return valid JSON: {e}", code="MODEL_OUTPUT_INVALID") from e

        if not isinstance(parsed, dict) or not isinstance(usage_data, dict):
            raise LiveLLMError("Model response must be a JSON object")
        usage = LLMUsage(
            prompt_tokens=int(usage_data.get("prompt_tokens", 0)),
            completion_tokens=int(usage_data.get("completion_tokens", 0)),
            latency_ms=latency_ms,
        )

        requires_clarification = parsed.get("requires_clarification", False)
        clarification_q = parsed.get("clarification_question")
        if requires_clarification and (not clarification_q or not str(clarification_q).strip()):
            clarification_q = "The question contains ambiguity. Please specify whether you mean total volume/count or total monetary value."

        try:
            return GeneratedCandidate(
                sql=parsed.get("sql"),
                assumptions=parsed.get("assumptions") or [],
                requires_clarification=requires_clarification,
                clarification_question=clarification_q,
                usage=usage,
            )
        except Exception as e:
            raise LiveLLMError(f"Model JSON failed candidate validation: {e}", code="MODEL_OUTPUT_INVALID") from e


_live_provider_singleton: OpenAICompatibleProvider | None = None


def get_live_llm_provider(settings: Settings | None = None) -> OpenAICompatibleProvider:
    """Factory for singleton live LLM provider."""
    global _live_provider_singleton
    cfg = settings or get_settings()
    api_base, model, api_key = cfg.get_effective_llm_config()
    if not cfg.llm_provider or not api_key or not api_key.strip() or not model.strip() or not api_base.strip():
        raise LiveLLMError("LLM configuration is incomplete", code="CONFIG_ERROR")
    if _live_provider_singleton is None:
        _live_provider_singleton = OpenAICompatibleProvider(
            api_base=api_base,
            model=model,
            api_key=api_key,
            max_response_bytes=cfg.max_request_bytes,
        )
    return _live_provider_singleton
