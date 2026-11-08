"""Detect aggregation grains that can multiply through physical join relations."""

from __future__ import annotations

from sqlglot import exp
from sqlglot.optimizer.scope import traverse_scope
from querylens.domain.schema import CatalogSnapshot


class SemanticWarning:
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message


def analyze_ast_semantics(ast: exp.Expression, snapshot: CatalogSnapshot) -> list[SemanticWarning]:
    metadata = {(table.namespace, table.name): table for table in snapshot.tables}
    for scope in traverse_scope(ast):
        if not isinstance(scope.expression, exp.Select) or not scope.expression.args.get("joins"):
            continue
        sources = {
            alias: source for alias, (_, source) in scope.selected_sources.items() if isinstance(source, exp.Table)
        }
        aggregates = [
            node
            for node in scope.walk()
            if isinstance(node, (exp.Sum, exp.Count, exp.Avg)) and not isinstance(node.this, exp.Distinct)
        ]
        if not aggregates:
            continue
        child_aliases: dict[str, set[str]] = {}
        for child_alias, source in sources.items():
            table = metadata.get((source.db, source.name))
            if table is None:
                continue
            for fk in table.foreign_keys:
                if fk.cardinality not in ("many_to_one", "unknown"):
                    continue
                for parent_alias, parent in sources.items():
                    if (
                        parent.name == fk.target_table
                        and parent.db == (fk.target_namespace or source.db)
                        and parent_alias != child_alias
                    ):
                        child_aliases.setdefault(parent_alias, set()).add(child_alias)
        for parent_alias, children in child_aliases.items():
            parent_aggregate = any(
                any(column.table == parent_alias for column in aggregate.find_all(exp.Column))
                or isinstance(aggregate.this, exp.Star)
                for aggregate in aggregates
            )
            if parent_aggregate or len(children) > 1:
                return [
                    SemanticWarning(
                        "FANOUT_RISK",
                        "Aggregation joins a parent grain to child rows. Counts or totals may be multiplied; pre-aggregate children or verify the intended grain.",
                    )
                ]
        # Unknown joins have no FK guarantee; flag multi-join aggregate queries conservatively.
        if len(scope.expression.args.get("joins") or []) >= 2:
            return [
                SemanticWarning(
                    "FANOUT_RISK",
                    "Multiple joined sources feed an aggregate. Verify join cardinality and pre-aggregate independent child tables to avoid inflated totals.",
                )
            ]
    return []
