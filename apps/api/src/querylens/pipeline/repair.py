"""Repair policy and attempt budget controller (Contracts C07, C08)."""

from __future__ import annotations

from dataclasses import dataclass, field
import time

from querylens.pipeline.errors import ClassifiedError


@dataclass
class RunAttemptBudget:
    """Run-scoped time, token, and attempt bounds."""

    start_time: float = field(default_factory=time.monotonic)
    total_deadline_sec: float = 30.0
    cleanup_reserve_sec: float = 5.0
    cumulative_tokens: int = 0
    max_cumulative_tokens: int = 16000
    max_attempts: int = 3  # 1 initial generation + at most 2 repairs

    def add_tokens(self, tokens: int) -> None:
        self.cumulative_tokens += tokens

    def time_remaining(self, now: float | None = None) -> float:
        current = now if now is not None else time.monotonic()
        elapsed = current - self.start_time
        return max(0.0, self.total_deadline_sec - elapsed)

    def is_deadline_exceeded(self, now: float | None = None) -> bool:
        return self.time_remaining(now) <= self.cleanup_reserve_sec

    def is_tokens_exhausted(self) -> bool:
        return self.cumulative_tokens >= self.max_cumulative_tokens


@dataclass(frozen=True)
class RepairDecision:
    """Decision indicating whether pipeline may proceed with a repair attempt."""

    can_repair: bool
    reason: str | None = None


class RepairPolicy:
    """Enforces retry policy rules for query repair."""

    def decide(
        self,
        error: ClassifiedError,
        attempt_number: int,
        budget: RunAttemptBudget,
    ) -> RepairDecision:
        # 1. Budget and resource exhaustion checks
        if budget.is_tokens_exhausted():
            return RepairDecision(can_repair=False, reason="TOKEN_BUDGET_EXCEEDED")

        if budget.is_deadline_exceeded():
            return RepairDecision(can_repair=False, reason="DEADLINE_EXCEEDED")

        # 2. Maximum attempts check (1 initial + 2 repairs = 3 attempts total)
        if attempt_number >= budget.max_attempts:
            return RepairDecision(can_repair=False, reason="MAX_ATTEMPTS_EXCEEDED")

        # 3. Category repairability check
        if not error.repairable:
            if error.category == "policy":
                reason = "POLICY_VIOLATION"
            elif error.category == "permission":
                reason = "PERMISSION_DENIED"
            elif error.category == "timeout":
                reason = "TIMEOUT"
            elif error.category == "ambiguous_intent":
                reason = "AMBIGUOUS_INTENT"
            else:
                reason = "NON_REPAIRABLE_CATEGORY"
            return RepairDecision(can_repair=False, reason=reason)

        return RepairDecision(can_repair=True)
