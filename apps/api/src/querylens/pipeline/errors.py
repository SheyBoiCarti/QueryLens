"""Pipeline error taxonomy and data models (Contracts C06, C08, C11)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

ErrorCategory = Literal[
    "syntax",
    "unknown_identifier",
    "aggregate",
    "fan_out",
    "dialect",
    "function",
    "policy",
    "permission",
    "timeout",
    "connection",
    "model",
    "ambiguous_intent",
    "unknown",
]


@dataclass(frozen=True)
class ClassifiedError:
    """Classified and sanitized pipeline error representation."""

    category: ErrorCategory
    code: str
    safe_message: str
    repairable: bool
    identifier_hints: list[str] = field(default_factory=list)

    @property
    def error_signature(self) -> str:
        return f"{self.category}:{self.code}"


class PipelineError(Exception):
    """Base exception for pipeline processing."""


class AmbiguousIntentError(PipelineError):
    """Raised when intent cannot be resolved without user clarification."""


class FanoutDetectedError(PipelineError):
    """Raised when a query causes metric fan-out duplication."""


class RepairLimitExceededError(PipelineError):
    """Raised when maximum repair attempts have been exhausted."""


class RepairStalledError(PipelineError):
    """Raised when repair repeats identical SQL or consecutive identical errors."""
