"""Streaming RFC 4180 CSV generation and formula injection neutralization (Contracts C07, C09)."""

from __future__ import annotations

from typing import Any

FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r", "\n", "|")
MAX_RESULT_BYTES = 1048576  # 1MB limit for serialized results


class ResultTooLargeError(Exception):
    """Raised when serialized export exceeds byte bounds."""


def escape_csv_field(value: Any) -> str:
    """Neutralize formula injection and apply RFC 4180 escaping without stripping whitespace."""
    if value is None:
        return '""'

    val_str = str(value)

    # Check for dangerous formula injection prefixes (including after whitespace/control chars)
    if val_str and val_str[0] in FORMULA_PREFIXES:
        val_str = "'" + val_str
    else:
        # Check after leading space characters
        stripped = val_str.lstrip(" \t\r\n")
        if stripped and stripped[0] in ("=", "+", "-", "@", "|"):
            val_str = "'" + val_str

    # RFC 4180 double-quote escaping
    escaped_quotes = val_str.replace('"', '""')
    return f'"{escaped_quotes}"'


def generate_csv_string(
    columns: list[dict[str, Any]],
    rows: list[dict[str, Any]],
    max_bytes: int = MAX_RESULT_BYTES,
) -> str:
    """Generate complete RFC 4180 CSV string with preflight byte budgeting."""
    header_fields = [escape_csv_field(c["name"]) for c in columns]
    lines = [",".join(header_fields)]

    for row in rows:
        row_fields = [escape_csv_field(row.get(c["name"])) for c in columns]
        lines.append(",".join(row_fields))

    csv_output = "\r\n".join(lines)
    utf8_bytes = csv_output.encode("utf-8")

    if len(utf8_bytes) > max_bytes:
        raise ResultTooLargeError(
            f"Serialized CSV payload of {len(utf8_bytes)} bytes exceeds maximum allowed limit of {max_bytes} bytes"
        )

    return csv_output
