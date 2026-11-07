"""Type and identifier normalization for PostgreSQL and MySQL (Contracts C05, C09)."""

from __future__ import annotations

import re
from querylens.domain.schema import CanonicalType


def normalize_data_type(db_type_str: str) -> CanonicalType:
    """Normalize vendor data type string into canonical type."""
    t = db_type_str.lower().strip()

    # Integers
    if re.search(r"\b(int|integer|smallint|bigint|tinyint|mediumint|serial|bigserial)\b", t):
        if "tinyint(1)" in t:
            return "boolean"
        return "integer"

    # Decimals / Numeric
    if re.search(r"\b(decimal|numeric|money|smallmoney)\b", t):
        return "decimal"

    # Floats
    if re.search(r"\b(float|double|real|double precision)\b", t):
        return "float"

    # Booleans
    if re.search(r"\b(bool|boolean)\b", t):
        return "boolean"

    # Dates
    if re.search(r"\b(date)\b", t) and not re.search(r"\b(datetime)\b", t):
        return "date"

    # Timestamps / Datetimes
    if re.search(r"\b(datetime|timestamp|timestamptz|time)\b", t):
        return "datetime"

    # Text / String fallback
    return "string"


def normalize_namespace(engine: str, raw_schema: str | None) -> str:
    """Normalize namespace for target engine."""
    if engine == "postgresql":
        return raw_schema or "public"
    elif engine == "mysql":
        return raw_schema or "defaultdb"
    return "public"
