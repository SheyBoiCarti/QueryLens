"""Structural AST semantic analyzer for fan-out detection (Contracts C05, C06, C10)."""

from __future__ import annotations

from sqlglot import exp
from querylens.domain.schema import CatalogSnapshot


class SemanticWarning:
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message


def analyze_ast_semantics(ast: exp.Expression, snapshot: CatalogSnapshot) -> list[SemanticWarning]:
    """Inspect query AST for join fan-out risk across multiple 1:N relations."""
    warnings: list[SemanticWarning] = []

    # Map tables with one-to-many child relationships
    # e.g., if parent table P is joined with two child tables C1, C2 in same scope with SUM/COUNT aggregates
    for select in ast.find_all(exp.Select):
        from_table = select.args.get("from")
        joins = select.args.get("joins") or []

        if len(joins) >= 2:
            # Check if multiple aggregates exist
            agg_count = len(list(select.find_all(exp.Sum))) + len(list(select.find_all(exp.Count)))
            if agg_count >= 2:
                # Potential fan-out risk
                warnings.append(
                    SemanticWarning(
                        code="FANOUT_RISK",
                        message="Query joins multiple tables with aggregate functions in single scope. Verify that child grains do not distort sums.",
                    )
                )
                break

    return warnings
