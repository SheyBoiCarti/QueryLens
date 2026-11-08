"""Bound source values before transfer, then enforce the exact JSON byte budget."""

from __future__ import annotations

import json
from typing import Any
from sqlglot import exp

from querylens.config import get_settings
from querylens.execution.serializer import SerializationError, serialize_result_set
from querylens.sql.parse import parse_query


def metadata_probe_sql(sql: str, engine: str) -> str:
    """Preserve flat output labels; MySQL derived tables reject duplicate names."""
    ast = parse_query(sql, engine)
    ast.set("limit", exp.Limit(expression=exp.Literal.number(0)))
    ast.set("offset", None)
    return ast.sql(dialect="postgres" if engine == "postgresql" else engine, comments=False)


def bounded_source_sql(sql: str, column_count: int, engine: str) -> str:
    """Keep oversized values on the source server instead of allocating them in DBAPI.

    The metadata-only probe supplies the number of outputs. Synthetic derived
    column names also handle duplicate result labels without changing positions.
    A final flag reports rejected rows; values are never silently truncated.
    """
    if column_count < 1:
        raise SerializationError("Query must return at least one column")
    settings = get_settings()
    quote = '"' if engine == "postgresql" else "`"
    names = [f"{quote}__ql_c{index}{quote}" for index in range(column_count)]
    references = [f"q.{name}" for name in names]
    if engine == "postgresql":
        lengths = [
            f"COALESCE(pg_catalog.octet_length(pg_catalog.convert_to(CAST({ref} AS text), 'UTF8')), 0)"
            for ref in references
        ]
    else:
        lengths = [f"COALESCE(OCTET_LENGTH(CAST({ref} AS CHAR CHARACTER SET utf8mb4)), 0)" for ref in references]
    too_large = " OR ".join(
        [f"{length} > {settings.max_cell_bytes}" for length in lengths]
        + [f"({' + '.join(lengths) or '0'}) > {settings.max_result_bytes}"]
    )
    projections = [f"CASE WHEN b.{quote}__ql_oversize{quote} THEN NULL ELSE b.{name} END" for name in names]
    projections.append(f"b.{quote}__ql_oversize{quote}")
    inner = sql.rstrip().removesuffix(";")
    guarded = f"SELECT q.*, ({too_large}) AS {quote}__ql_oversize{quote} FROM ({inner}) AS q ({', '.join(names)})"
    return f"SELECT {', '.join(projections)} FROM ({guarded}) AS b"


def fetch_bounded_rows(
    cursor: Any, columns_desc: list[Any], max_rows: int
) -> tuple[list[dict[str, str]], list[dict[str, Any]], bool]:
    """Read one guarded row at a time; retain at most the public result budget."""
    columns, _, _ = serialize_result_set(columns_desc, [], max_rows)
    rows: list[dict[str, Any]] = []
    typed: set[str] = set()
    total_bytes = len(json.dumps(columns, ensure_ascii=False).encode("utf-8")) + 512
    while True:
        raw = cursor.fetchone()
        if raw is None:
            return columns, rows, False
        if len(rows) == max_rows:
            return columns, rows, True
        if raw[-1]:
            raise SerializationError("Source row exceeds the cell or result byte budget")
        row_columns, serialized, _ = serialize_result_set(columns_desc, [raw[:-1]], 1)
        row = serialized[0]
        total_bytes += len(json.dumps(row, ensure_ascii=False).encode("utf-8")) + 1
        if total_bytes > get_settings().max_result_bytes:
            raise SerializationError("Result exceeds the JSON byte budget")
        for index, column in enumerate(row_columns):
            if column["name"] not in typed and row[column["name"]] is not None:
                columns[index] = column
                typed.add(column["name"])
        rows.append(row)
