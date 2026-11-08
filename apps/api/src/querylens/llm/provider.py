"""Abstract base class for LLM generation providers (Contracts C01, C08)."""

from __future__ import annotations

from abc import ABC, abstractmethod
from querylens.llm.protocol import GeneratedCandidate


class LLMProvider(ABC):
    """Abstract generation provider."""

    @abstractmethod
    async def generate(
        self,
        question: str,
        dialect: str,
        schema_context: str,
        timeout_sec: float = 15.0,
    ) -> GeneratedCandidate:
        """Generate structured candidate from natural language question and schema context."""
        pass
