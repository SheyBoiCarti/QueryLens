"""Result-set comparator supporting multiset matching, exact decimals, and float tolerance (Contracts C09, C10)."""

from __future__ import annotations

from decimal import Decimal
import math
from typing import Any, Sequence


class ComparisonMismatchError(Exception):
    """Raised when query output does not match expected reference results."""
    pass


def compare_cells(actual: Any, expected: Any, float_tol: float = 1e-6) -> bool:
    """Compare two cell values according to Contract C10 semantics."""
    if actual is None and expected is None:
        return True
    if (actual is None) != (expected is None):
        return False

    # Boolean check
    if isinstance(actual, bool) or isinstance(expected, bool):
        return actual is expected

    # Exact decimal and integer comparison
    if isinstance(actual, (int, Decimal, str)) and isinstance(expected, (int, Decimal, str)):
        try:
            d_act = Decimal(str(actual))
            d_exp = Decimal(str(expected))
            return d_act == d_exp
        except Exception:
            pass

    # Float comparison with tolerance
    if isinstance(actual, float) or isinstance(expected, float):
        try:
            f_act = float(actual)
            f_exp = float(expected)
            if not math.isfinite(f_act) or not math.isfinite(f_exp):
                return False
            return math.isclose(f_act, f_exp, abs_tol=float_tol, rel_tol=float_tol)
        except Exception:
            return False

    # String comparison (case and whitespace preserved)
    return str(actual) == str(expected)


def compare_rows(row_a: dict[str, Any] | Sequence[Any], row_b: dict[str, Any] | Sequence[Any]) -> bool:
    """Compare two rows positionally or by keys."""
    vals_a = list(row_a.values()) if isinstance(row_a, dict) else list(row_a)
    vals_b = list(row_b.values()) if isinstance(row_b, dict) else list(row_b)

    if len(vals_a) != len(vals_b):
        return False

    return all(compare_cells(ca, cb) for ca, cb in zip(vals_a, vals_b))


def compare_result_sets(
    actual_rows: list[Any],
    expected_rows: list[Any],
    ordered: bool = False,
) -> bool:
    """Compare two result sets.
    
    If ordered=True: compares positionally in exact order.
    If ordered=False: compares as a multiset (bag) retaining duplicate multiplicity.
    """
    if len(actual_rows) != len(expected_rows):
        return False

    if ordered:
        return all(compare_rows(a, e) for a, e in zip(actual_rows, expected_rows))

    # Multiset (bag) comparison with one-to-one matching
    unmatched_expected = list(expected_rows)
    for act in actual_rows:
        matched_idx = -1
        for idx, exp in enumerate(unmatched_expected):
            if compare_rows(act, exp):
                matched_idx = idx
                break
        if matched_idx == -1:
            return False
        unmatched_expected.pop(matched_idx)

    return len(unmatched_expected) == 0
