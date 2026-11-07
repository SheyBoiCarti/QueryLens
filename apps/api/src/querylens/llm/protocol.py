"""LLM candidate schema and usage metadata protocol (Contracts C01, C07, C08)."""

from __future__ import annotations

from typing import Any
from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictBaseModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class LLMUsage(StrictBaseModel):
    prompt_tokens: int = 0
    completion_tokens: int = 0
    latency_ms: int = 0


class GeneratedCandidate(StrictBaseModel):
    """Strictly bounded model candidate response (Contract C08)."""
    sql: str | None = Field(default=None, max_length=32768)
    assumptions: list[str] = Field(default_factory=list, max_length=10)
    requires_clarification: bool = False
    clarification_question: str | None = Field(default=None, max_length=500)
    usage: LLMUsage = Field(default_factory=LLMUsage)

    @model_validator(mode="after")
    def validate_clarification_or_sql(self) -> GeneratedCandidate:
        if self.requires_clarification:
            if not self.clarification_question or not self.clarification_question.strip():
                raise ValueError("clarification_question is required and must be non-empty when requires_clarification is True")
        else:
            if not self.sql or not self.sql.strip():
                raise ValueError("sql is required and must be non-empty when requires_clarification is False")

        # Validate assumption item lengths
        for a in self.assumptions:
            if len(a) > 500:
                raise ValueError(f"Assumption exceeds 500 characters: {a[:50]}...")

        return self
