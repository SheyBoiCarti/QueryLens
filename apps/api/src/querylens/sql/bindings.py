"""Driver statement compilation and parameter binding (Contract C06)."""

from __future__ import annotations

import re
from collections.abc import Mapping
from querylens.domain.analytics import BoundParameter


def compile_driver_statement(
    sql: str, engine: str, bindings: tuple[BoundParameter, ...]
) -> tuple[str, Mapping[str, object]]:
    """Render placeholder nodes as psycopg/PyMySQL named parameters without substituting values.

    Correctly escapes literal percent signs for the parameter protocol.
    """
    if not bindings:
        return sql, {}

    binding_names = {b.name for b in bindings}
    params: dict[str, object] = {b.name: b.value for b in bindings}

    working_sql = sql
    # In MySQL, sqlglot outputs :name for placeholders.
    # Convert :name to %(name)s for PyMySQL pyformat protocol.
    if engine == "mysql":

        def repl_colon(m: re.Match[str]) -> str:
            name = m.group(1)
            if name in binding_names:
                return f"%({name})s"
            return m.group(0)

        # Match :param where param is word characters not preceded by : (to avoid :: cast if any)
        working_sql = re.sub(r"(?<!:):([A-Za-z_][A-Za-z0-9_]*)", repl_colon, working_sql)

    # In both drivers with parameter dicts, literal '%' must be escaped to '%%'.
    # Match valid parameter tokens '%(name)s' vs existing '%%' vs unescaped '%'
    pattern = re.compile(r"(%\([A-Za-z_][A-Za-z0-9_]*\)s|%%|%)")
    parts: list[str] = []
    last_end = 0
    for match in pattern.finditer(working_sql):
        matched = match.group(0)
        parts.append(working_sql[last_end : match.start()])
        if matched.startswith("%(") and matched[2:-2] in binding_names:
            parts.append(matched)
        elif matched == "%%":
            parts.append("%%")
        else:
            parts.append("%%")
        last_end = match.end()
    parts.append(working_sql[last_end:])

    return "".join(parts), params
