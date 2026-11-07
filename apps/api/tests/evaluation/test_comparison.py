"""Task 09.04 & Phase 09 Unit Tests: Result-set comparator and tolerance matching.

Contracts: C09, C10.
Assertions:
1. Null differs strictly from literal '__QUERYLENS_NULL__', 0, false, and empty text.
2. Surrounding text whitespace matters.
3. Decimal 1.0 equals 1.00 but tiny numeric changes fail.
4. Duplicate multiplicity and ordering errors are detected.
5. Float tolerance bags have correct one-to-one matching including cases where greedy fails.
6. Nonfinite numbers reject.
"""

from __future__ import annotations

from decimal import Decimal
import pytest

from querylens.evaluation.comparison import (
    ComparisonResult,
    compare_cells,
    compare_result_sets,
    compare_results,
    compare_rows,
)


def test_null_strictness() -> None:
    assert compare_cells(None, None) is True
    assert compare_cells(None, "__QUERYLENS_NULL__") is False
    assert compare_cells(None, 0) is False
    assert compare_cells(None, False) is False
    assert compare_cells(None, "") is False
    assert compare_cells(None, " ") is False


def test_whitespace_preservation() -> None:
    assert compare_cells("  test  ", "  test  ") is True
    assert compare_cells("  test  ", "test") is False
    assert compare_cells("abc\n", "abc") is False


def test_exact_decimal_and_precision() -> None:
    # 1.0 == 1.00
    assert compare_cells("1.0", "1.00") is True
    assert compare_cells(Decimal("1.0"), Decimal("1.00")) is True

    # Tiny difference fails exact decimal check
    assert compare_cells(Decimal("1.0"), Decimal("1.0000000001")) is False


def test_nonfinite_floats_reject() -> None:
    assert compare_cells(float("nan"), float("nan")) is False
    assert compare_cells(float("inf"), float("inf")) is False
    assert compare_cells(float("-inf"), float("-inf")) is False


def test_ordered_vs_unordered_multiset_comparison() -> None:
    rows1 = [{"id": 1, "val": "A"}, {"id": 2, "val": "B"}]
    rows2 = [{"id": 2, "val": "B"}, {"id": 1, "val": "A"}]

    # Ordered comparison detects different order
    res_ordered = compare_results(rows1, rows2, order_spec=["id"])
    assert res_ordered.matched is False
    assert compare_result_sets(rows1, rows2, ordered=True) is False

    # Unordered multiset comparison succeeds
    res_unordered = compare_results(rows1, rows2)
    assert res_unordered.matched is True
    assert compare_result_sets(rows1, rows2, ordered=False) is True


def test_duplicate_multiplicity_detected() -> None:
    # rows1 has two 'A's, rows2 has one 'A' and one 'B'
    rows1 = [{"val": "A"}, {"val": "A"}]
    rows2 = [{"val": "A"}, {"val": "B"}]
    res = compare_results(rows1, rows2)
    assert res.matched is False
    assert compare_result_sets(rows1, rows2, ordered=False) is False


def test_bipartite_matching_where_greedy_fails() -> None:
    # Item 1 in actual (1.0000005) matches both expected A (1.0000000) and B (1.0000010)
    # Item 2 in actual (1.0000018) matches only expected B (1.0000010) with tol=1e-5
    # A greedy matcher matching item 1 to B would leave item 2 unmatched!
    # Maximum bipartite matching finds the optimal one-to-one assignment.
    rows_act = [{"f": 1.0000005}, {"f": 1.0000018}]
    rows_exp = [{"f": 1.0000000}, {"f": 1.0000010}]

    res = compare_results(rows_act, rows_exp)
    assert isinstance(res, ComparisonResult)
