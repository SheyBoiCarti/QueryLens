"""Result serialization, exact numeric encoding, and payload size bounds (Contracts C07, C09)."""

from __future__ import annotations

import datetime
from decimal import Decimal
import math
from typing import Any

from querylens.domain.schema import CanonicalType
from querylens.schema.normalizer import normalize_data_type

MAX_CELL_BYTES = 65536
MAX_RESULT_BYTES = 1048576


class SerializationError(Exception):
    """Raised when serialization limits are exceeded or invalid types encountered."""
    pass


def serialize_cell(value: Any) -> tuple[Any, CanonicalType, int]:
    """Serialize single cell value into canonical JSON-compatible form.
    
    Returns:
        (serialized_value, canonical_type, byte_length)
    """
    if value is None:
        return None, "string", 4

    if isinstance(value, bool):
        return value, "boolean", 5

    # Integers serialize as exact strings (Contract C09: prevent JS Number truncation)
    if isinstance(value, int):
        s_val = str(value)
        b_len = len(s_val.encode("utf-8"))
        if b_len > MAX_CELL_BYTES:
            raise SerializationError(f"Cell size exceeds {MAX_CELL_BYTES} bytes")
        return s_val, "integer", b_len

    # Decimals serialize as exact strings
    if isinstance(value, Decimal):
        s_val = str(value)
        b_len = len(s_val.encode("utf-8"))
        if b_len > MAX_CELL_BYTES:
            raise SerializationError(f"Cell size exceeds {MAX_CELL_BYTES} bytes")
        return s_val, "decimal", b_len

    # Finite floats serialize as numbers
    if isinstance(value, float):
        if not math.isfinite(value):
            raise SerializationError("Non-finite float (NaN or Infinity) is not permitted")
        return value, "float", 16

    # Dates
    if isinstance(value, datetime.date) and not isinstance(value, datetime.datetime):
        s_val = value.isoformat()
        return s_val, "date", len(s_val)

    # Datetimes normalize to UTC ISO string
    if isinstance(value, datetime.datetime):
        if value.tzinfo is None:
            # Assume UTC
            value = value.replace(tzinfo=datetime.timezone.utc)
        else:
            value = value.astimezone(datetime.timezone.utc)
        s_val = value.isoformat()
        return s_val, "datetime", len(s_val)

    # Text / String fallback
    s_val = str(value)
    b_len = len(s_val.encode("utf-8"))
    if b_len > MAX_CELL_BYTES:
        raise SerializationError(f"Cell size {b_len} exceeds {MAX_CELL_BYTES} bytes")
    return s_val, "string", b_len


def serialize_result_set(
    columns_desc: list[Any],
    raw_rows: list[Sequence[Any]],
    max_rows: int,
) -> tuple[list[dict[str, str]], list[dict[str, Any]], bool]:
    """Serialize full database result set.
    
    Returns:
        (columns_metadata, rows, truncated)
    """
    # Detect truncation: if raw_rows has max_rows + 1, truncated is True
    truncated = False
    if len(raw_rows) > max_rows:
        truncated = True
        exposed_rows = raw_rows[:max_rows]
    else:
        exposed_rows = raw_rows

    total_bytes = 0
    serialized_rows: list[dict[str, Any]] = []

    # Prepare column headers
    col_names = [col[0] for col in columns_desc]
    col_types: dict[str, CanonicalType] = {}

    for row in exposed_rows:
        row_dict: dict[str, Any] = {}
        for col_name, cell_val in zip(col_names, row):
            s_val, c_type, b_len = serialize_cell(cell_val)
            row_dict[col_name] = s_val
            total_bytes += b_len + len(col_name)

            if col_name not in col_types and cell_val is not None:
                col_types[col_name] = c_type

        if total_bytes > MAX_RESULT_BYTES:
            raise SerializationError(f"Total result set exceeds {MAX_RESULT_BYTES} bytes (RESULT_TOO_LARGE)")

        serialized_rows.append(row_dict)

    # Build final columns metadata list
    columns_meta = []
    for col in columns_desc:
        c_name = col[0]
        c_type = col_types.get(c_name, "string")
        columns_meta.append({
            "name": c_name,
            "type": c_type,
            "db_type": str(col[1]) if len(col) > 1 else "unknown",
        })

    return columns_meta, serialized_rows, truncated
