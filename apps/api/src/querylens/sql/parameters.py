"""SQL parameter slots, extraction, and typed AST compilation (Contract C06)."""

from __future__ import annotations

import datetime as dt
import math
from collections.abc import Mapping
from decimal import Decimal
from typing import Annotated, Any, Literal, Self
from pydantic import Field, TypeAdapter, ValidationError, model_validator
from sqlglot import exp

from querylens.config import get_settings
from querylens.domain.analytics import (
    BoundParameter,
    FrozenMetadata,
    ResolvedDateRange,
    ResolvedParameters,
    Scalar,
)
from querylens.domain.query import ValidatedArtifact
from querylens.domain.schema import CanonicalType, CatalogSnapshot
from querylens.sql.limits import bound_query_limits
from querylens.sql.parse import parse_query
from querylens.sql.policy import validate_query_artifact


class ParameterCompilationError(Exception):
    """Raised when parameter compilation, type validation, or target resolution fails."""

    pass


class DateRangeFixed(FrozenMetadata):
    mode: Literal["fixed"]
    start_date: Annotated[str, Field(pattern=r"^\d{4}-\d{2}-\d{2}$")]
    end_date_inclusive: Annotated[str, Field(pattern=r"^\d{4}-\d{2}-\d{2}$")]

    @model_validator(mode="after")
    def validate_dates(self) -> Self:
        try:
            start = dt.date.fromisoformat(self.start_date)
            end = dt.date.fromisoformat(self.end_date_inclusive)
        except ValueError as exc:
            raise ValueError(f"Invalid calendar date: {exc}") from exc
        if start > end:
            raise ValueError("start_date must be less than or equal to end_date_inclusive")
        return self


class DateRangeThisMonth(FrozenMetadata):
    mode: Literal["this_month"]


class DateRangeThisYear(FrozenMetadata):
    mode: Literal["this_year"]


DateRangeInput = Annotated[DateRangeFixed | DateRangeThisMonth | DateRangeThisYear, Field(discriminator="mode")]
_date_range_adapter = TypeAdapter(DateRangeInput)


class ParameterTarget(FrozenMetadata):
    scope: Annotated[str, Field(min_length=1, max_length=100)] = "root"
    predicate_path: Annotated[str, Field(min_length=1, max_length=200)]
    namespace: Annotated[str, Field(min_length=1, max_length=255)]
    table_name: Annotated[str, Field(min_length=1, max_length=255)]
    column_name: Annotated[str, Field(min_length=1, max_length=255)]
    operator: Literal["=", "!=", "<>", "<", "<=", ">", ">=", "IN", "BETWEEN", "date_range"]
    secondary_predicate_path: Annotated[str, Field(min_length=1, max_length=200)] | None = None
    secondary_operator: Annotated[str, Field(min_length=1, max_length=20)] | None = None


class ParameterDefinition(FrozenMetadata):
    slot_id: Annotated[str, Field(pattern=r"^[A-Za-z0-9_]{1,100}$")]
    name: Annotated[str, Field(pattern=r"^[A-Za-z_][A-Za-z0-9_]{0,99}$")]
    label: Annotated[str, Field(min_length=1, max_length=200)]
    param_type: Literal["date_range", "category", "result_count"]
    source_type: CanonicalType
    target: ParameterTarget | None = None
    allowed_values: tuple[Scalar, ...] | None = None
    default_value: Any = None

    @model_validator(mode="after")
    def validate_definition(self) -> Self:
        if self.param_type == "result_count":
            if self.source_type != "integer":
                raise ValueError("result_count must have integer source_type")
            if self.target is not None:
                raise ValueError("result_count cannot have a target")
            if self.default_value is not None:
                if type(self.default_value) is not int or self.default_value < 1 or self.default_value > 1000:
                    raise ValueError("result_count default_value must be an integer between 1 and 1000")
        elif self.param_type == "category":
            if self.target is None:
                raise ValueError("category parameter requires a target")
            if self.allowed_values is not None:
                if len(self.allowed_values) == 0:
                    raise ValueError("allowed_values cannot be empty if specified")
                if len(self.allowed_values) > 100:
                    raise ValueError("allowed_values exceeds maximum of 100")
        elif self.param_type == "date_range":
            if self.target is None:
                raise ValueError("date_range parameter requires a target")
            if self.source_type not in ("date", "datetime"):
                raise ValueError("date_range source_type must be date or datetime")
        return self


def extract_eligible_parameters(
    template_sql: str,
    snapshot: CatalogSnapshot,
    engine: str,
    author_limit: int | None,
    default_max_rows: int = 100,
) -> list[ParameterDefinition]:
    """Extract candidate parameter slots from unambiguous conjunctive WHERE predicates."""
    definitions: list[ParameterDefinition] = []

    try:
        ast = parse_query(template_sql, dialect=engine)
    except Exception:
        return definitions

    # Only single SELECT statements are eligible for predicate slots
    if isinstance(ast, exp.Select):
        # Reject if HAVING is present
        if ast.args.get("having") is None:
            where_node = ast.args.get("where")
            if where_node is not None:
                # If there are any OR nodes in WHERE, reject WHERE predicates
                if not where_node.find(exp.Or):
                    _extract_where_predicates(where_node.this, snapshot, definitions)

    # Result count is server-owned and always included
    rc_default = min(author_limit, default_max_rows) if author_limit is not None else default_max_rows
    definitions.append(
        ParameterDefinition(
            slot_id="result_count",
            name="result_count",
            label="Result count",
            param_type="result_count",
            source_type="integer",
            default_value=rc_default,
        )
    )

    return definitions


def _extract_where_predicates(
    where_expr: exp.Expression,
    snapshot: CatalogSnapshot,
    definitions: list[ParameterDefinition],
) -> None:
    # Flatten conjunctive ANDs
    conjuncts: list[exp.Expression] = []

    def _collect_and(node: Any) -> None:
        if isinstance(node, exp.And):
            _collect_and(node.left)
            _collect_and(node.right)
        else:
            conjuncts.append(node)

    _collect_and(where_expr)

    # Find table lookup helper
    table_lookup = {t.name.lower(): t for t in snapshot.tables}

    # Group date comparisons by column
    date_candidates: dict[str, dict[str, Any]] = {}
    category_added = False

    for idx, c in enumerate(conjuncts):
        # 1. Equality predicate (category candidate)
        if isinstance(c, exp.EQ) and not category_added:
            col_node = c.left if isinstance(c.left, exp.Column) else (c.right if isinstance(c.right, exp.Column) else None)
            lit_node = c.right if isinstance(c.right, exp.Literal) else (c.left if isinstance(c.left, exp.Literal) else None)
            if col_node and lit_node:
                col_name = col_node.name
                table_name = col_node.table or (snapshot.tables[0].name if len(snapshot.tables) == 1 else None)
                if table_name and table_name.lower() in table_lookup:
                    table_meta = table_lookup[table_name.lower()]
                    col_meta = next((cm for cm in table_meta.columns if cm.name.lower() == col_name.lower()), None)
                    if col_meta and col_meta.canonical_type in ("string", "integer", "float", "boolean"):
                        default_val: Any = lit_node.this
                        if col_meta.canonical_type == "integer":
                            try:
                                default_val = int(lit_node.this)
                            except ValueError:
                                pass
                        elif col_meta.canonical_type in ("float", "decimal"):
                            try:
                                default_val = float(lit_node.this)
                            except ValueError:
                                pass
                        elif col_meta.canonical_type == "boolean":
                            default_val = str(lit_node.this).lower() in ("true", "1")

                        definitions.append(
                            ParameterDefinition(
                                slot_id=f"category_{col_name}",
                                name=col_name,
                                label=col_name.replace("_", " ").title(),
                                param_type="category",
                                source_type=col_meta.canonical_type,
                                target=ParameterTarget(
                                    scope="root",
                                    predicate_path=f"where.{idx}",
                                    namespace=table_meta.namespace or "public",
                                    table_name=table_meta.name,
                                    column_name=col_meta.name,
                                    operator="=",
                                ),
                                default_value=default_val,
                            )
                        )
                        category_added = True
                        continue

        # 2. Date comparisons (GTE, GT, LTE, LT)
        if isinstance(c, (exp.GTE, exp.GT, exp.LTE, exp.LT)):
            col_node = c.left if isinstance(c.left, exp.Column) else None
            lit_node = c.right if isinstance(c.right, exp.Literal) else None
            if col_node and lit_node:
                col_name = col_node.name
                table_name = col_node.table or (snapshot.tables[0].name if len(snapshot.tables) == 1 else None)
                if table_name and table_name.lower() in table_lookup:
                    table_meta = table_lookup[table_name.lower()]
                    col_meta = next((cm for cm in table_meta.columns if cm.name.lower() == col_name.lower()), None)
                    if col_meta and col_meta.canonical_type in ("date", "datetime"):
                        op_name = ">=" if isinstance(c, exp.GTE) else (">" if isinstance(c, exp.GT) else ("<=" if isinstance(c, exp.LTE) else "<"))
                        entry = date_candidates.setdefault(col_name.lower(), {
                            "col_meta": col_meta,
                            "table_meta": table_meta,
                            "ops": {},
                        })
                        entry["ops"][op_name] = (idx, lit_node.this)

    # Process date candidates into date_range parameters
    for col_lower, info in date_candidates.items():
        ops = info["ops"]
        col_meta = info["col_meta"]
        table_meta = info["table_meta"]
        col_name = col_meta.name

        start_date: str | None = None
        end_date_inclusive: str | None = None
        start_idx: int | None = None
        end_idx: int | None = None

        if ">=" in ops:
            start_idx, start_date = ops[">="]
        elif ">" in ops:
            start_idx, start_date = ops[">"]

        if "<" in ops:
            end_idx, raw_end = ops["<"]
            # Exclusive end: subtract 1 day for inclusive UI end
            try:
                excl_d = dt.date.fromisoformat(raw_end[:10])
                end_date_inclusive = (excl_d - dt.timedelta(days=1)).isoformat()
            except ValueError:
                end_date_inclusive = raw_end[:10]
        elif "<=" in ops:
            end_idx, raw_end = ops["<="]
            end_date_inclusive = raw_end[:10]

        if start_date and end_date_inclusive and start_idx is not None and end_idx is not None:
            definitions.append(
                ParameterDefinition(
                    slot_id=f"date_range_{col_name}",
                    name=col_name,
                    label=col_name.replace("_", " ").title(),
                    param_type="date_range",
                    source_type=col_meta.canonical_type,
                    target=ParameterTarget(
                        scope="root",
                        predicate_path=f"where.{start_idx}",
                        namespace=table_meta.namespace or "public",
                        table_name=table_meta.name,
                        column_name=col_name,
                        operator=">=",
                        secondary_predicate_path=f"where.{end_idx}",
                        secondary_operator="<",
                    ),
                    default_value={
                        "mode": "fixed",
                        "start_date": start_date[:10],
                        "end_date_inclusive": end_date_inclusive,
                    },
                )
            )


def compile_parameterized_query(
    template_sql: str,
    definitions: tuple[ParameterDefinition, ...],
    values: Mapping[str, object],
    snapshot: CatalogSnapshot,
    connection_id: str,
    engine: str,
    max_rows: int,
    author_limit: int | None,
    now: dt.datetime,
) -> ValidatedArtifact:
    """Verify slots, resolve defaults/UTC presets, install placeholder AST nodes, and mint a token."""
    try:
        ast = parse_query(template_sql, dialect=engine)
    except Exception as exc:
        raise ParameterCompilationError(f"Failed to parse template SQL: {exc}") from exc

    effective_max_rows = max_rows
    bound_parameters: list[BoundParameter] = []
    resolved_dates: list[ResolvedDateRange] = []
    supplied_values: dict[str, Any] = {}

    for param_def in definitions:
        # Resolve value from input or default
        val = values.get(param_def.name)
        if val is None:
            val = values.get(param_def.slot_id)
        if val is None:
            val = param_def.default_value
        if val is None:
            raise ParameterCompilationError(f"Missing required parameter value for {param_def.name}")

        supplied_values[param_def.name] = val

        if param_def.param_type == "result_count":
            if type(val) is not int or type(val) is bool:
                raise ParameterCompilationError("result_count must be an integer")
            if val < 1 or val > 1000:
                raise ParameterCompilationError("result_count must be between 1 and 1000")
            effective_max_rows = min(val, author_limit) if author_limit is not None else val
            effective_max_rows = min(effective_max_rows, get_settings().max_max_rows)

        elif param_def.param_type == "category":
            if param_def.target is None:
                raise ParameterCompilationError(f"Category parameter {param_def.name} missing target")

            # Check scalar
            if not isinstance(val, (str, int, float, bool)) or (isinstance(val, float) and not math.isfinite(val)):
                raise ParameterCompilationError(f"Category value for {param_def.name} must be a finite scalar")

            # Validate type matches declared source_type
            if param_def.source_type == "string" and type(val) is not str:
                raise ParameterCompilationError(f"Value for {param_def.name} must be a string")
            elif param_def.source_type == "integer" and (type(val) is not int or type(val) is bool):
                raise ParameterCompilationError(f"Value for {param_def.name} must be an integer")
            elif param_def.source_type in ("float", "decimal") and (not isinstance(val, (int, float, Decimal)) or type(val) is bool):
                raise ParameterCompilationError(f"Value for {param_def.name} must be numeric")
            elif param_def.source_type == "boolean" and type(val) is not bool:
                raise ParameterCompilationError(f"Value for {param_def.name} must be a boolean")

            # Allowed values check
            if param_def.allowed_values is not None:
                if not any(type(val) is type(a) and val == a for a in param_def.allowed_values):
                    raise ParameterCompilationError(f"Value '{val}' is not in allowed_values for {param_def.name}")

            placeholder_name = f"p_{param_def.slot_id}"
            bound_parameters.append(
                BoundParameter(name=placeholder_name, scalar_type=param_def.source_type, value=val)
            )

            # Install placeholder in AST
            _install_category_placeholder(ast, param_def.target, placeholder_name)

        elif param_def.param_type == "date_range":
            if param_def.target is None:
                raise ParameterCompilationError(f"Date range parameter {param_def.name} missing target")

            # Parse DateRangeInput
            try:
                date_input = _date_range_adapter.validate_python(val)
            except ValidationError as exc:
                raise ParameterCompilationError(f"Invalid DateRangeInput for {param_def.name}: {exc}") from exc

            start_d: dt.date
            end_exclusive_d: dt.date

            if date_input.mode == "fixed":
                start_d = dt.date.fromisoformat(date_input.start_date)
                end_inc = dt.date.fromisoformat(date_input.end_date_inclusive)
                if start_d > end_inc:
                    raise ParameterCompilationError("Date range start_date cannot be after end_date_inclusive")
                end_exclusive_d = end_inc + dt.timedelta(days=1)
            elif date_input.mode == "this_month":
                now_utc = now.astimezone(dt.timezone.utc)
                start_d = dt.date(now_utc.year, now_utc.month, 1)
                if now_utc.month == 12:
                    end_exclusive_d = dt.date(now_utc.year + 1, 1, 1)
                else:
                    end_exclusive_d = dt.date(now_utc.year, now_utc.month + 1, 1)
            elif date_input.mode == "this_year":
                now_utc = now.astimezone(dt.timezone.utc)
                start_d = dt.date(now_utc.year, 1, 1)
                end_exclusive_d = dt.date(now_utc.year + 1, 1, 1)

            start_scalar: dt.date | dt.datetime
            end_scalar: dt.date | dt.datetime
            if param_def.source_type == "datetime":
                start_scalar = dt.datetime(start_d.year, start_d.month, start_d.day, 0, 0, 0, tzinfo=dt.timezone.utc)
                end_scalar = dt.datetime(end_exclusive_d.year, end_exclusive_d.month, end_exclusive_d.day, 0, 0, 0, tzinfo=dt.timezone.utc)
            else:
                start_scalar = start_d
                end_scalar = end_exclusive_d

            resolved_dates.append(
                ResolvedDateRange(
                    slot_id=param_def.slot_id,
                    start=start_scalar,
                    end_exclusive=end_scalar,
                )
            )

            p_start = f"p_{param_def.slot_id}_start"
            p_end = f"p_{param_def.slot_id}_end"
            bound_parameters.append(
                BoundParameter(name=p_start, scalar_type=param_def.source_type, value=start_scalar)
            )
            bound_parameters.append(
                BoundParameter(name=p_end, scalar_type=param_def.source_type, value=end_scalar)
            )

            # Install placeholders in AST
            _install_date_range_placeholders(ast, param_def.target, p_start, p_end)

    # Bound limits
    bounded_ast, _ = bound_query_limits(ast.copy(), max_rows=effective_max_rows)

    dialect_map = {"postgresql": "postgres", "mysql": "mysql"}
    target_dialect = dialect_map.get(engine, engine)
    canonical_sql = bounded_ast.sql(dialect=target_dialect, comments=False)
    template_out = ast.sql(dialect=target_dialect, comments=False)

    bindings_tuple = tuple(bound_parameters)
    resolved_params = ResolvedParameters(
        bindings=bindings_tuple,
        values=supplied_values,
        resolved_dates=tuple(resolved_dates),
        max_rows=effective_max_rows,
    )

    artifact = validate_query_artifact(
        canonical_sql,
        connection_id=connection_id,
        engine=engine,
        snapshot=snapshot,
        max_rows=effective_max_rows,
        bindings=bindings_tuple,
    )

    return ValidatedArtifact(
        token=artifact.token,
        template_sql=template_out,
        author_limit=author_limit,
        resolved_parameters=resolved_params,
    )


def _install_category_placeholder(ast: exp.Expression, target: ParameterTarget, placeholder_name: str) -> None:
    found = False
    for eq in ast.find_all(exp.EQ):
        col_node = eq.left if isinstance(eq.left, exp.Column) else (eq.right if isinstance(eq.right, exp.Column) else None)
        if col_node and col_node.name.lower() == target.column_name.lower():
            if eq.left is col_node:
                eq.set("expression", exp.Placeholder(this=placeholder_name))
            else:
                eq.set("this", exp.Placeholder(this=placeholder_name))
            found = True
            break
    if not found:
        raise ParameterCompilationError(f"Target column '{target.column_name}' predicate not found in template SQL")


def _install_date_range_placeholders(
    ast: exp.Expression,
    target: ParameterTarget,
    p_start: str,
    p_end: str,
) -> None:
    found_start = False
    found_end = False

    gte_nodes: list[exp.Expression] = list(ast.find_all(exp.GTE)) + list(ast.find_all(exp.GT))
    for node in gte_nodes:
        if isinstance(node, (exp.GTE, exp.GT)) and isinstance(node.left, exp.Column) and node.left.name.lower() == target.column_name.lower():
            node.set("expression", exp.Placeholder(this=p_start))
            found_start = True
            break

    lte_nodes: list[exp.Expression] = list(ast.find_all(exp.LTE)) + list(ast.find_all(exp.LT))
    for node in lte_nodes:
        if isinstance(node, (exp.LTE, exp.LT)) and isinstance(node.left, exp.Column) and node.left.name.lower() == target.column_name.lower():
            node.set("expression", exp.Placeholder(this=p_end))
            found_end = True
            break

    if not (found_start or found_end):
        raise ParameterCompilationError(f"Date range predicates for '{target.column_name}' not found in template SQL")
