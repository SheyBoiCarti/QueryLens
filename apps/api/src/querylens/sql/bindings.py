"""Compile driver parameters from SQL placeholder AST nodes only."""

from __future__ import annotations

from collections.abc import Mapping
import uuid

from sqlglot import exp

from querylens.domain.analytics import BoundParameter
from querylens.sql.parse import parse_query


def compile_driver_statement(
    sql: str, engine: str, bindings: tuple[BoundParameter, ...]
) -> tuple[str, Mapping[str, object]]:
    if not bindings:
        return sql, {}
    params = {binding.name: binding.value for binding in bindings}
    if len(params) != len(bindings):
        raise ValueError("Duplicate driver binding")
    ast = parse_query(sql, dialect=engine)
    # Unique markers separate generated protocol syntax from every literal,
    # identifier and comment. Escape data before installing driver placeholders.
    prefix = "ql_binding_" + uuid.uuid4().hex
    while prefix in sql:
        prefix = "ql_binding_" + uuid.uuid4().hex
    markers: dict[str, str] = {}
    for index, node in enumerate(list(ast.find_all(exp.Placeholder))):
        if node.name not in params:
            raise ValueError("Unbound SQL placeholder")
        marker = f"{prefix}_{index}"
        markers[marker] = node.name
        node.replace(exp.Var(this=marker))
    dialect = "postgres" if engine == "postgresql" else engine
    rendered = ast.sql(dialect=dialect, comments=False).replace("%", "%%")
    for marker, name in markers.items():
        rendered = rendered.replace(marker, f"%({name})s")
    return rendered, params
