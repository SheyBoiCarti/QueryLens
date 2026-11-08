"""Derive physical provenance and conservative meaning from authorized SQL ASTs."""

from __future__ import annotations

from decimal import Decimal
import hashlib
from typing import cast

import sqlglot
from sqlglot import exp
from sqlglot.optimizer.scope import traverse_scope

from querylens.domain.analytics import (
    AppliedFilter,
    MetricReference,
    ObjectReference,
    ResolvedParameters,
    RunContext,
    RunOrigin,
)
from querylens.domain.schema import CatalogSnapshot
from querylens.semantics.versions import SemanticContext
from querylens.sql.identifiers import resolve_identifiers


def _literal(node):
    if isinstance(node, exp.Literal):
        if node.is_string:
            return node.this
        value = Decimal(node.this)
        return int(value) if value == value.to_integral_value() else str(value)
    if isinstance(node, exp.Boolean):
        return node.this
    if isinstance(node, exp.Neg) and isinstance(node.this, exp.Literal) and not node.this.is_string:
        value = Decimal(node.this.this).copy_negate()
        return int(value) if value == value.to_integral_value() else str(value)
    raise ValueError("Unsupported literal")


def _conjuncts(node):
    if isinstance(node, exp.And):
        return _conjuncts(node.this) + _conjuncts(node.expression)
    return [node]


_OPERATORS = {exp.EQ: "=", exp.NEQ: "!=", exp.GT: ">", exp.GTE: ">=", exp.LT: "<", exp.LTE: "<="}


def _metric_literal(node):
    if isinstance(node, exp.Literal) and not node.is_string:
        return Decimal(node.this)
    if isinstance(node, exp.Neg) and isinstance(node.this, exp.Literal) and not node.this.is_string:
        return Decimal(node.this.this).copy_negate()
    return _literal(node)


def _predicate(node, resolve, *, metric=False):
    literal = _metric_literal if metric else _literal
    if metric and isinstance(node, exp.Not):
        column, operator, value = _predicate(node.this, resolve, metric=True)
        if operator in ("IN", "IS NULL"):
            return column, {"IN": "NOT IN", "IS NULL": "IS NOT NULL"}[operator], value
        raise ValueError("Unsupported negation")
    if (
        metric
        and isinstance(node, exp.Is)
        and isinstance(node.this, exp.Column)
        and isinstance(node.expression, exp.Null)
    ):
        return resolve(node.this), "IS NOT NULL" if node.args.get("negate") else "IS NULL", None
    if type(node) in _OPERATORS and isinstance(node.this, exp.Column):
        return resolve(node.this), _OPERATORS[type(node)], literal(node.expression)
    if isinstance(node, exp.In) and isinstance(node.this, exp.Column) and not node.args.get("query"):
        return resolve(node.this), "IN", tuple(literal(item) for item in node.expressions)
    if isinstance(node, exp.Between) and isinstance(node.this, exp.Column):
        return resolve(node.this), "BETWEEN", (_literal(node.args["low"]), _literal(node.args["high"]))
    raise ValueError("Unsupported predicate")


def _typed(value):
    # Compare values with explicit type tags, so bool/number and numeric/string never alias.
    if isinstance(value, tuple):
        return tuple(_typed(item) for item in value)
    if type(value) in (int, float, Decimal):
        decimal = Decimal(str(value))
        sign, digits, exponent = decimal.as_tuple()
        if decimal.is_zero():
            return "number", (0, (0,), 0)
        # Strip insignificant zeros without Decimal.normalize(), which rounds using
        # the active decimal context and can collapse distinct long literals.
        if not isinstance(exponent, int):
            raise ValueError("Non-finite metric filter")
        while digits and digits[-1] == 0:
            digits = digits[:-1]
            exponent += 1
        return "number", (sign, digits, exponent)
    return type(value).__name__, value


def _matches_metric(ast, scope, metric, snapshot):
    """Only a plain single-table exact aggregation/filter/grain match is proof."""
    if not isinstance(ast, exp.Select) or len(list(traverse_scope(ast))) != 1:
        return False
    if any(ast.args.get(name) for name in ("joins", "distinct", "having", "qualify", "windows", "with_")):
        return False
    if ast.find(exp.Window) or len(scope.selected_sources) != 1:
        return False
    source = next(iter(scope.selected_sources.values()))[1]
    if not isinstance(source, exp.Table):
        return False
    # The DSL describes the full physical relation. Any relation modifier may
    # change that population (sampling, ONLY, partitions, temporal versions,
    # pivots, etc.), so only a bare qualified table plus an ordinary alias is
    # eligible. An allowlist also fails closed for future SQLGlot modifiers.
    if any(value for key, value in source.args.items() if key not in {"this", "db", "catalog", "alias"}):
        return False
    alias = source.args.get("alias")
    if alias and any(value for key, value in alias.args.items() if key != "this"):
        return False
    dsl = metric.dsl
    try:
        dsl.validate_against_snapshot(snapshot)
    except ValueError:
        return False
    parts = dsl.table.split(".")
    if source.name != parts[-1] or (len(parts) == 2 and source.db != parts[0]):
        return False
    projections = [item.unalias() for item in ast.expressions]
    aggregates = [item for item in projections if isinstance(item, exp.AggFunc)]
    if len(aggregates) != 1:
        return False
    agg = aggregates[0]
    kind = {exp.Sum: "sum", exp.Count: "count", exp.Avg: "avg", exp.Min: "min", exp.Max: "max"}.get(type(agg))
    operand = agg.this
    if isinstance(operand, exp.Distinct):
        if kind != "count" or len(operand.expressions) != 1:
            return False
        kind, operand = "count_distinct", operand.expressions[0]
    measure = operand.name if isinstance(operand, exp.Column) else "*" if isinstance(operand, exp.Star) else None
    if kind != dsl.aggregation or measure != dsl.measure_column:
        return False
    group = ast.args.get("group")
    groups = group.expressions if group else []
    if any(not isinstance(item, exp.Column) for item in groups) or (
        group and any(group.args.get(k) for k in ("rollup", "cube", "grouping_sets", "totals"))
    ):
        return False
    grains = [item.name for item in groups]
    if sorted(grains) != sorted(item.split(".")[-1] for item in dsl.grain):
        return False
    others = [item for item in projections if item is not agg]
    if any(not isinstance(item, exp.Column) for item in others) or sorted(item.name for item in others) != sorted(
        grains
    ):
        return False
    try:
        where = ast.args.get("where")
        actual = (
            [_predicate(item, lambda column: column.name, metric=True) for item in _conjuncts(where.this)]
            if where
            else []
        )
        mapping = {
            "eq": "=",
            "neq": "!=",
            "gt": ">",
            "gte": ">=",
            "lt": "<",
            "lte": "<=",
            "in": "IN",
            "not_in": "NOT IN",
            "is_null": "IS NULL",
            "is_not_null": "IS NOT NULL",
        }
        expected = []
        for f in dsl.filters:
            if f.operator not in mapping:
                return False
            value = (
                tuple(f.value)
                if f.operator in ("in", "not_in") and isinstance(f.value, list)
                else None
                if f.operator in ("is_null", "is_not_null")
                else f.value
            )
            expected.append((f.column.split(".")[-1], mapping[f.operator], value))

        def signature(items):
            return sorted((col, op, repr(_typed(value))) for col, op, value in items)

        return signature(actual) == signature(expected)
    except (ValueError, TypeError):
        return False


def build_run_context(
    template_sql: str,
    author_limit: int | None,
    question: str,
    origin: RunOrigin,
    snapshot: CatalogSnapshot,
    semantics: SemanticContext,
    resolved_parameters: ResolvedParameters | None = None,
) -> RunContext:
    dialect = "postgres" if snapshot.engine == "postgresql" else snapshot.engine
    ast = cast(exp.Expression, sqlglot.parse_one(template_sql, read=dialect))
    resolve_identifiers(ast, snapshot)
    bindings = {item.name: item.value for item in resolved_parameters.bindings} if resolved_parameters else {}
    # Binding values are used only to describe supported predicates, never to execute SQL.
    for placeholder in list(ast.find_all(exp.Placeholder)):
        if placeholder.name in bindings:
            value = bindings[placeholder.name]
            if hasattr(value, "isoformat"):
                value = value.isoformat()
            placeholder.replace(exp.convert(value))
    objects = {}
    filters: list[AppliedFilter] = []
    for scope in traverse_scope(ast):
        sources = {
            alias: source for alias, (_, source) in scope.selected_sources.items() if isinstance(source, exp.Table)
        }
        for source in sources.values():
            key = (source.db, source.name, None)
            objects[key] = ObjectReference(namespace=source.db, table_name=source.name)

        def resolve(column):
            source = sources.get(column.table)
            if source is None:
                raise ValueError("Derived column")
            table = next(t for t in snapshot.tables if t.namespace == source.db and t.name == source.name)
            col = next(c for c in table.columns if c.name == column.name)
            key = (source.db, source.name, column.name)
            ref = ObjectReference(
                namespace=source.db,
                table_name=source.name,
                column_name=column.name,
                canonical_type=col.canonical_type,
                db_type=col.db_type,
            )
            objects[key] = ref
            return ref

        for column in scope.columns:
            try:
                resolve(column)
            except (ValueError, StopIteration):
                pass
        where = scope.expression.args.get("where")
        if where:
            for i, predicate in enumerate(_conjuncts(where.this)):
                try:
                    column, operator, value = _predicate(predicate, resolve)
                    slot = hashlib.sha256(f"{len(filters)}:{predicate.sql(dialect=dialect)}".encode()).hexdigest()[:24]
                    filters.append(AppliedFilter(slot_id=slot, column=column, operator=operator, value=value))
                except (ValueError, StopIteration):
                    continue
    scopes = list(traverse_scope(ast))
    metrics = tuple(
        MetricReference(id=m.id, key=m.key, version=m.version, dsl_hash=m.dsl.compute_hash())
        for m in semantics.metrics
        if m.enabled and scopes and _matches_metric(ast, scopes[-1], m, snapshot)
    )
    keys = set(objects)
    labels = tuple(
        label for label in semantics.labels if (label.namespace, label.table_name, label.column_name) in keys
    )
    tables = ", ".join(sorted({f"{ref.namespace}.{ref.table_name}" for ref in objects.values()}))
    # Canonical SQL remains the complete authoritative fallback. Free-form wording cannot prove business meaning.
    effective = f"Query result from {tables or 'the validated SQL'}."
    if metrics and origin != "manual_sql":
        effective = "Verified metric " + ", ".join(metric.key for metric in metrics) + f" from {tables}."
    if filters:
        effective += (
            " Filters: "
            + "; ".join(
                f"{f.column.namespace}.{f.column.table_name}.{f.column.column_name} {f.operator} {f.value!r}"
                for f in filters
            )
            + "."
        )
    return RunContext(
        effective_question=effective,
        canonical_sql_template=template_sql,
        author_limit=author_limit,
        applied_filters=tuple(filters),
        metric_references=metrics,
        label_references=labels,
        referenced_objects=tuple(objects.values()),
        snapshot_hash=snapshot.snapshot_hash,
        policy_version=snapshot.policy_version,
        semantic_version=semantics.semantic_version,
    )
