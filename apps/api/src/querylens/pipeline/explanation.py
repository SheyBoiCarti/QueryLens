"""Deterministic presentation derived only while authorized rows are available."""

from __future__ import annotations

import datetime as dt
import math
from decimal import Decimal, InvalidOperation

from querylens.domain.analytics import RunContext, RunOrigin
from querylens.domain.presentation import PresentationMetadata, VerifiedDefinition
from querylens.semantics.versions import SemanticContext

NUMERIC_TYPES = {"integer", "decimal", "float"}
JS_SAFE_INTEGER = 9007199254740991


def _number(value, kind):
    if isinstance(value, bool) or not isinstance(value, (str, int, float, Decimal)):
        return None
    try:
        decimal = Decimal(str(value))
        if not decimal.is_finite():
            return None
        if kind == "integer" and decimal != decimal.to_integral_value():
            return None
        return decimal
    except (InvalidOperation, ValueError):
        return None


def _safe_plot(value, kind):
    decimal = _number(value, kind)
    if decimal is None:
        return False
    try:
        number = float(decimal)
        # Shared JS rule: Number -> shortest decimal -> exact decimal must roundtrip.
        # Python's shortest repr agrees on significant digits; exponent formatting is immaterial.
        if not math.isfinite(number) or Decimal(str(number)) != decimal:
            return False
        if decimal == decimal.to_integral_value() and abs(decimal) > JS_SAFE_INTEGER:
            return False
        return True
    except (OverflowError, ValueError):
        return False


def _date_key(value, kind):
    if not isinstance(value, str) or not value:
        raise ValueError("Invalid date key")
    if kind == "date":
        parsed = dt.date.fromisoformat(value)
        if parsed.isoformat() != value:
            raise ValueError("Noncanonical date")
        return parsed.toordinal()
    parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    if "T" not in value and " " not in value:
        raise ValueError("Missing timestamp")
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.UTC)
    return parsed.timestamp()


def derive_presentation(
    columns,
    rows,
    context: RunContext,
    origin: RunOrigin,
    truncated: bool,
    *,
    semantics: SemanticContext | None = None,
    units: tuple[str, ...] = (),
) -> PresentationMetadata:
    definitions = []
    if semantics:
        for reference in context.metric_references:
            for metric in semantics.metrics:
                if (
                    metric.enabled
                    and metric.id == reference.id
                    and metric.version == reference.version
                    and metric.dsl.compute_hash() == reference.dsl_hash
                ):
                    definitions.append(
                        VerifiedDefinition(
                            id=metric.id,
                            key=metric.key,
                            version=metric.version,
                            name=metric.name,
                            description=metric.description,
                            units=metric.dsl.units,
                        )
                    )
    known_units = {unit for unit in (*units, *(definition.units for definition in definitions)) if unit}
    warnings = ["Results are truncated; the displayed rows do not represent a complete result."] if truncated else []
    title = "Query result"
    if definitions and origin != "manual_sql":
        title = ", ".join(definition.name for definition in definitions)
    explanation = f"{len(rows)} returned row" + ("s." if len(rows) != 1 else ".")
    base = PresentationMetadata(
        title=title,
        explanation=explanation,
        date_scope=tuple(f for f in context.applied_filters if f.column.canonical_type in ("date", "datetime")),
        verified_definitions=tuple(definitions),
        units=next(iter(known_units)) if len(known_units) == 1 else None,
        warnings=tuple(warnings),
    )
    if len(known_units) > 1:
        return base
    if len(columns) == 1 and len(rows) == 1 and columns[0]["type"] in NUMERIC_TYPES:
        name = columns[0]["name"]
        value = rows[0].get(name)
        if _number(value, columns[0]["type"]) is not None:
            exact = str(value)
            return base.model_copy(
                update={
                    "explanation": f"{name}: {exact}.",
                    "chart_type": "single_value",
                    "y_column": name,
                    "value": exact,
                }
            )
    if len(columns) != 2 or not 1 <= len(rows) <= 50:
        return base
    x, y = columns
    if x["type"] in NUMERIC_TYPES and y["type"] not in NUMERIC_TYPES:
        x, y = y, x
    if x["type"] not in ("date", "datetime", "string", "boolean") or y["type"] not in NUMERIC_TYPES:
        return base
    keys = []
    decimals: dict[float, Decimal] = {}
    for row in rows:
        key = row.get(x["name"])
        value = row.get(y["name"])
        if key is None or key == "" or not _safe_plot(value, y["type"]):
            return base
        try:
            if x["type"] in ("date", "datetime"):
                key = _date_key(key, x["type"])
            elif x["type"] == "boolean":
                if type(key) is not bool:
                    return base
            elif not isinstance(key, str):
                return base
            if key in keys:
                return base
            keys.append(key)
            numeric = float(value)
            exact_decimal = Decimal(str(value))
            if numeric in decimals and decimals[numeric] != exact_decimal:
                return base
            decimals[numeric] = exact_decimal
        except (ValueError, TypeError, OverflowError):
            return base
    order = (
        tuple(sorted(range(len(rows)), key=lambda i: keys[i]))
        if x["type"] in ("date", "datetime")
        else tuple(range(len(rows)))
    )
    return base.model_copy(
        update={
            "chart_type": "line" if x["type"] in ("date", "datetime") else "bar",
            "x_column": x["name"],
            "y_column": y["name"],
            "plot_row_order": order,
        }
    )
