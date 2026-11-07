"""Low-cardinality Prometheus-style stage metrics tracking (Contracts C07, C08, C11)."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
import threading
from typing import Any

# Strictly allowlisted low-cardinality labels
ALLOWED_STAGES = {"schema_ranking", "candidate_generation", "ast_validation", "execution", "repair"}
ALLOWED_OUTCOMES = {"success", "error", "rejected", "timeout", "cancelled"}


@dataclass
class MetricsRegistry:
    """In-memory low-cardinality stage metrics registry."""

    _lock: threading.Lock = field(default_factory=threading.Lock)
    _stage_counts: Counter[tuple[str, str]] = field(default_factory=Counter)
    _security_events: Counter[str] = field(default_factory=Counter)

    def record_stage(self, stage: str, outcome: str) -> None:
        """Record a pipeline stage execution with strictly bounded label cardinality."""
        norm_stage = stage if stage in ALLOWED_STAGES else "unknown_stage"
        norm_outcome = outcome if outcome in ALLOWED_OUTCOMES else "unknown_outcome"

        with self._lock:
            self._stage_counts[(norm_stage, norm_outcome)] += 1

    def record_security_event(self, event_type: str) -> None:
        """Record security-relevant events (e.g. CSRF failure, SQL policy violation)."""
        safe_type = event_type.replace(" ", "_").lower()[:32]
        with self._lock:
            self._security_events[safe_type] += 1

    def get_snapshot(self) -> dict[str, Any]:
        """Return snapshot of recorded metrics."""
        with self._lock:
            return {
                "stage_executions": {f"{s}_{o}": count for (s, o), count in self._stage_counts.items()},
                "security_events": dict(self._security_events),
            }


_registry_singleton = MetricsRegistry()


def record_stage_metrics(run_id: str, stage: str, outcome: str) -> None:
    """Record metrics for a pipeline stage."""
    _registry_singleton.record_stage(stage, outcome)


def record_security_event(event_type: str) -> None:
    """Record security-relevant event."""
    _registry_singleton.record_security_event(event_type)


def get_metrics_snapshot() -> dict[str, Any]:
    """Retrieve current metrics snapshot."""
    return _registry_singleton.get_snapshot()
