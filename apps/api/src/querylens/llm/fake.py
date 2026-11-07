"""Dialect-aware exact-match fake provider for deterministic testing (Contracts C01, C08)."""

from __future__ import annotations

import re
from querylens.llm.protocol import GeneratedCandidate, LLMUsage
from querylens.llm.provider import LLMProvider


class FakeLLMProvider(LLMProvider):
    """Offline exact-match provider. Unknown questions fail explicitly without default queries."""

    def __init__(self) -> None:
        self._canned: dict[tuple[str, str], GeneratedCandidate] = {}
        self._canned_sequences: dict[tuple[str, str], list[GeneratedCandidate]] = {}
        self._init_defaults()

    def _normalize(self, q: str) -> str:
        return re.sub(r"\s+", " ", q.strip().lower())

    def _normalize_dialect(self, d: str) -> str:
        dl = d.strip().lower()
        return "postgres" if dl in ("postgres", "postgresql") else dl

    def register_response(
        self,
        dialect: str,
        question: str,
        candidate: GeneratedCandidate,
    ) -> None:
        """Register a canned response for a dialect and question."""
        key = (self._normalize_dialect(dialect), self._normalize(question))
        self._canned[key] = candidate

    def register_sequence(
        self,
        dialect: str,
        question: str,
        candidates: list[GeneratedCandidate],
    ) -> None:
        """Register a sequence of candidates returned on consecutive calls."""
        key = (self._normalize_dialect(dialect), self._normalize(question))
        self._canned_sequences[key] = list(candidates)

    def _init_defaults(self) -> None:
        # Standard smoke questions
        smoke_q = "how many customers are there"
        for d in ["postgresql", "mysql"]:
            self.register_response(
                d,
                smoke_q,
                GeneratedCandidate(
                    sql="SELECT COUNT(*) AS total_customers FROM customers;",
                    assumptions=["Counts all active and inactive customer records"],
                    requires_clarification=False,
                    usage=LLMUsage(prompt_tokens=150, completion_tokens=30, latency_ms=25),
                ),
            )

        ambiguous_q = "show me the best"
        for d in ["postgresql", "mysql"]:
            self.register_response(
                d,
                ambiguous_q,
                GeneratedCandidate(
                    requires_clarification=True,
                    clarification_question="What metric defines 'the best' (e.g. highest revenue, most orders, highest rating)?",
                    usage=LLMUsage(prompt_tokens=100, completion_tokens=25, latency_ms=20),
                ),
            )

    async def generate(
        self,
        question: str,
        dialect: str,
        schema_context: str,
        timeout_sec: float = 15.0,
    ) -> GeneratedCandidate:
        norm_d = self._normalize_dialect(dialect)
        norm_q = self._normalize(question)
        key = (norm_d, norm_q)
        if key in self._canned_sequences and self._canned_sequences[key]:
            return self._canned_sequences[key].pop(0)

        if key in self._canned:
            return self._canned[key]

        # Check question alone across any dialect
        for (d, q), cand in self._canned.items():
            if q == norm_q:
                return cand

        # Contract C08: Unknown fake questions raise a test error; never default to SELECT 1
        raise ValueError(f"FakeLLMProvider received unknown question for {dialect}: '{question}'")


_fake_provider_singleton: FakeLLMProvider | None = None


def get_fake_llm_provider() -> FakeLLMProvider:
    global _fake_provider_singleton
    if _fake_provider_singleton is None:
        _fake_provider_singleton = FakeLLMProvider()
    return _fake_provider_singleton
