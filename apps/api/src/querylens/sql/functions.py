"""Function allowlist inspection and validation (Contract C06)."""

from __future__ import annotations

from sqlglot import exp

# Strictly allowlisted function names (lowercase)
ALLOWED_FUNCTIONS = {
    # Aggregates
    "count",
    "sum",
    "avg",
    "min",
    "max",
    # Math
    "abs",
    "round",
    "ceil",
    "ceiling",
    "floor",
    # Strings
    "concat",
    "lower",
    "upper",
    "trim",
    "ltrim",
    "rtrim",
    "substring",
    "substr",
    "length",
    "len",
    # Conditionals
    "coalesce",
    "nullif",
    "case",
    "cast",
    "try_cast",
    # Date/Time
    "extract",
    "date_trunc",
    "timestamp_trunc",
    "year",
    "month",
    "day",
    "hour",
    "minute",
    "second",
    "now",
    "current_timestamp",
    "current_date",
    # Window
    "row_number",
    "rank",
    "dense_rank",
}


class FunctionPolicyError(Exception):
    """Raised when an unapproved function is used in SQL."""

    pass


def validate_functions(ast: exp.Expression) -> None:
    """Inspect all function calls in AST and reject unapproved ones."""
    # An allowlisted bare name does not authorize a same-named source UDF.
    if any(isinstance(node.expression, exp.Func) for node in ast.find_all(exp.Dot)):
        raise FunctionPolicyError("Schema-qualified function calls are prohibited")
    if any(node.this == exp.DataType.Type.USERDEFINED for node in ast.find_all(exp.DataType)):
        raise FunctionPolicyError("User-defined cast types are prohibited")
    # Check all exp.Func subclasses
    for func_node in ast.find_all(exp.Func):
        # EXISTS, AND, OR are SQL syntax/connectors, not callable functions; still inspect subtree.
        if isinstance(func_node, (exp.Exists, exp.Connector, exp.And, exp.Or)):
            continue
        func_name = func_node.name.lower() if isinstance(func_node, exp.Anonymous) else func_node.sql_name().lower()
        if func_name not in ALLOWED_FUNCTIONS:
            raise FunctionPolicyError(f"Disallowed function '{func_name}' is not in policy allowlist")

    # Check anonymous function calls (e.g., custom or unparsed functions)
    for anon in ast.find_all(exp.Anonymous):
        name = anon.name.lower()
        if name not in ALLOWED_FUNCTIONS:
            raise FunctionPolicyError(f"Disallowed anonymous function '{name}' is not in policy allowlist")
