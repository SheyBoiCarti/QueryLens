"""Job state management and process restart reconciliation (Contract C08)."""

from __future__ import annotations

from querylens.observability.logging import log_event
from querylens.persistence.repositories.query_runs import QueryRunRepository


def reconcile_interrupted_runs() -> int:
    """Reconcile all 7 nonterminal query states upon process startup."""
    count = QueryRunRepository.mark_interrupted_runs()
    if count > 0:
        log_event("reconciled_interrupted_runs", count=count)
    return count
