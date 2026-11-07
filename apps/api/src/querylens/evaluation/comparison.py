"""Result-set comparator supporting multiset matching, exact decimals, and float tolerance (Contracts C09, C10)."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
import math
from typing import Any, Sequence


@dataclass(frozen=True)
class ComparisonResult:
    """Detailed outcome of a result-set comparison."""

    matched: bool
    reason: str | None = None

    def __bool__(self) -> bool:
        return self.matched


def compare_cells(actual: Any, expected: Any, float_tol: float = 1e-6) -> bool:
    """Compare two cell values according to Contract C10 semantics."""
    # 1. Null handling: None differs strictly from 0, false, empty string, and magic strings
    if actual is None and expected is None:
        return True
    if actual is None or expected is None:
        return False

    # 2. Boolean check (must precede int check because bool subclasses int in Python)
    if isinstance(actual, bool) or isinstance(expected, bool):
        if not (isinstance(actual, bool) and isinstance(expected, bool)):
            return False
        return actual is expected

    # 3. Non-finite float rejection
    if isinstance(actual, float) and (math.isnan(actual) or math.isinf(actual)):
        return False
    if isinstance(expected, float) and (math.isnan(expected) or math.isinf(expected)):
        return False

    # 4. Exact decimal and integer comparison (1.0 == 1.00)
    # Only if neither is a boolean
    if isinstance(actual, (int, Decimal)) or isinstance(expected, (int, Decimal)):
        try:
            d_act = Decimal(str(actual))
            d_exp = Decimal(str(expected))
            return d_act == d_exp
        except Exception:
            return False

    if isinstance(actual, str) and isinstance(expected, str):
        if "." in actual or "." in expected:
            try:
                d_act = Decimal(actual)
                d_exp = Decimal(expected)
                return d_act == d_exp
            except Exception:
                pass

    # 5. Float comparison with tolerance
    if isinstance(actual, float) or isinstance(expected, float):
        try:
            f_act = float(actual)
            f_exp = float(expected)
            return math.isclose(f_act, f_exp, abs_tol=float_tol, rel_tol=float_tol)
        except Exception:
            return False

    # 6. String comparison (preserves whitespace and case strictly)
    return str(actual) == str(expected)


def compare_rows(row_a: dict[str, Any] | Sequence[Any], row_b: dict[str, Any] | Sequence[Any]) -> bool:
    """Compare two rows positionally."""
    vals_a = list(row_a.values()) if isinstance(row_a, dict) else list(row_a)
    vals_b = list(row_b.values()) if isinstance(row_b, dict) else list(row_b)

    if len(vals_a) != len(vals_b):
        return False

    return all(compare_cells(ca, cb) for ca, cb in zip(vals_a, vals_b))


def compare_results(
    actual: list[Any],
    expected: list[Any],
    columns: list[str] | None = None,
    order_spec: list[str] | None = None,
) -> ComparisonResult:
    """Compare two result sets.
    
    If order_spec is provided: compares positionally in exact order.
    If order_spec is None/empty: compares as a multiset (bag) retaining duplicate multiplicity via maximum bipartite matching.
    """
    if len(actual) != len(expected):
        return ComparisonResult(
            matched=False,
            reason=f"Row count mismatch: actual={len(actual)}, expected={len(expected)}",
        )

    ordered = bool(order_spec and len(order_spec) > 0)
    if ordered:
        for idx, (a, e) in enumerate(zip(actual, expected)):
            if not compare_rows(a, e):
                return ComparisonResult(matched=False, reason=f"Order mismatch at row {idx}")
        return ComparisonResult(matched=True)

    # Maximum Bipartite Matching for multiset comparison
    n = len(actual)
    match_adj: list[list[int]] = [[] for _ in range(n)]
    for i, act in enumerate(actual):
        for j, exp in enumerate(expected):
            if compare_rows(act, exp):
                match_adj[i].append(j)

    # Augmenting path algorithm
    match_target: list[int] = [-1] * n

    def dfs(u: int, visited: list[bool]) -> bool:
        for v in match_adj[u]:
            if not visited[v]:
                visited[v] = True
                if match_target[v] < 0 or dfs(match_target[v], visited):
                    match_target[v] = u
                    return True
        return False

    matched_count = 0
    for u in range(n):
        visited = [False] * n
        if dfs(u, visited):
            matched_count += 1

    if matched_count == n:
        return ComparisonResult(matched=True)

    return ComparisonResult(
        matched=False,
        reason=f"Multiset mismatch: matched {matched_count} of {n} rows",
    )


def compare_result_sets(
    actual_rows: list[Any],
    expected_rows: list[Any],
    ordered: bool = False,
) -> bool:
    """Compare two result sets and return a boolean (Contract C04)."""
    order_spec = ["_order"] if ordered else None
    return compare_results(actual_rows, expected_rows, order_spec=order_spec).matched


