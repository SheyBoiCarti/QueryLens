"""OpenAI-compatible live LLM provider for Groq, OpenRouter, and OpenAI (Contracts C01, C08)."""

from __future__ import annotations

import json
import re
import time
from typing import Any
import httpx

from querylens.config import Settings, get_settings
from querylens.llm.protocol import GeneratedCandidate, LLMUsage
from querylens.llm.provider import LLMProvider


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
            "   - \"sql\": string or null (the SQL query, terminated with a semicolon)\n"
            "   - \"assumptions\": array of strings (business assumptions or filters applied, max 10 items, max 500 chars each)\n"
            "   - \"requires_clarification\": boolean\n"
            "   - \"clarification_question\": string or null (required if requires_clarification is true, max 500 chars)\n"
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
            f"Database Dialect: {dialect}\n\n"
            f"Schema Context:\n{schema_context}\n\n"
            f"User Question:\n{question}\n"
        )

        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": self._build_system_prompt(dialect)},
                {"role": "user", "content": user_content},
            ],
            "temperature": 0.0,
            "response_format": {"type": "json_object"},
        }

        start_time = time.monotonic()
        try:
            async with httpx.AsyncClient(timeout=timeout_sec) as client:
                resp = await client.post(url, json=payload, headers=headers)
        except httpx.TimeoutException as e:
            raise LiveLLMError(f"LLM request timed out after {timeout_sec:.1f}s", code="DEADLINE_EXCEEDED") from e
        except Exception as e:
            raise LiveLLMError(f"LLM connection error: {e}", code="MODEL_UNAVAILABLE") from e

        latency_ms = int((time.monotonic() - start_time) * 1000)

        if resp.status_code != 200:
            error_preview = resp.text[:500] if resp.text else f"Status {resp.status_code}"
            raise LiveLLMError(
                f"LLM provider error (status {resp.status_code}): {error_preview}",
                code="MODEL_UNAVAILABLE",
            )

        raw_bytes = resp.content
        if len(raw_bytes) > self.max_response_bytes:
            raise LiveLLMError(
                f"LLM response body exceeded max bound ({len(raw_bytes)} > {self.max_response_bytes} bytes)",
                code="MODEL_OUTPUT_INVALID",
            )

        try:
            body = resp.json()
            choice = body["choices"][0]["message"]["content"]
            usage_data = body.get("usage", {})
        except (KeyError, IndexError, json.JSONDecodeError) as e:
            raise LiveLLMError(f"Malformed LLM response structure: {e}", code="MODEL_OUTPUT_INVALID") from e

        cleaned = self._clean_json_text(choice)
        try:
            parsed = json.loads(cleaned)
        except json.JSONDecodeError as e:
            raise LiveLLMError(f"Model did not return valid JSON: {e}", code="MODEL_OUTPUT_INVALID") from e

        usage = LLMUsage(
            prompt_tokens=int(usage_data.get("prompt_tokens", 0)),
            completion_tokens=int(usage_data.get("completion_tokens", 0)),
            latency_ms=latency_ms,
        )

        requires_clarification = bool(parsed.get("requires_clarification", False))
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
    if _live_provider_singleton is None:
        cfg = settings or get_settings()
        api_base, model, api_key = cfg.get_effective_llm_config()
        if not api_key:
            raise LiveLLMError("LLM API key is required but not configured", code="CONFIG_ERROR")
        _live_provider_singleton = OpenAICompatibleProvider(
            api_base=api_base,
            model=model,
            api_key=api_key,
            max_response_bytes=cfg.max_request_bytes,
        )
    return _live_provider_singleton
