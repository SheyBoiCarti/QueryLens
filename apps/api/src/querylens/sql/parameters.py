"""SQL parameter slots, extraction, and typed AST compilation (Contract C06)."""

from __future__ import annotations

import datetime as dt
import math
from collections.abc import Mapping
from decimal import Decimal
from typing import Annotated, Any, Literal, Self, cast
from pydantic import Field, TypeAdapter, ValidationError, field_validator, model_validator
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
    db_type: Annotated[str, Field(min_length=1, max_length=255)] | None = None
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

    @field_validator("allowed_values", mode="before")
    @classmethod
    def convert_allowed_values(cls, v: Any) -> Any:
        if isinstance(v, list):
            return tuple(v)
        return v

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
                expected = {"string": str, "integer": int, "float": float, "decimal": float, "boolean": bool}.get(self.source_type)
                if any(type(value) is not expected and not (self.source_type in ("float", "decimal") and type(value) is int) for value in self.allowed_values):
                    raise ValueError("allowed_values must match the declared source_type")
            if self.default_value is not None:
                default_types: tuple[type, ...] | None = {
                    "string": (str,), "integer": (int,), "float": (int, float),
                    "decimal": (int, float), "boolean": (bool,),
                }.get(self.source_type)
                if default_types is None or type(self.default_value) not in default_types:
                    raise ValueError("default_value must match the declared source_type")
                if self.allowed_values is not None and not any(type(self.default_value) is type(value) and self.default_value == value for value in self.allowed_values):
                    raise ValueError("default_value must be one of allowed_values")
        elif self.param_type == "date_range":
            if self.target is None:
                raise ValueError("date_range parameter requires a target")
            if self.source_type not in ("date", "datetime"):
                raise ValueError("date_range source_type must be date or datetime")
            if self.default_value is not None:
                _date_range_adapter.validate_python(self.default_value)
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

    # Only a single root SELECT is supported. Resolve aliases to visible
    # physical catalog objects before exposing any predicate as a slot.
    if isinstance(ast, exp.Select):
        # Reject if HAVING is present
        if ast.args.get("having") is None and len(list(ast.find_all(exp.Select))) == 1:
            where_node = ast.args.get("where")
            if where_node is not None:
                # If there are any OR nodes in WHERE, reject WHERE predicates
                if not where_node.find(exp.Or):
                    _extract_where_predicates(ast, where_node.this, snapshot, definitions)

    # Result count is server-owned and always included
    if author_limit != 0:
        rc_default = min(author_limit, default_max_rows) if author_limit is not None else default_max_rows
        rc_default = max(1, rc_default)
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
    select: exp.Select,
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
    table_lookup: dict[str, Any] = {}
    from_node = select.args.get("from_")
    table_nodes = [from_node.this] if from_node and isinstance(from_node.this, exp.Table) else []
    table_nodes.extend(
        join.this for join in select.args.get("joins", []) if isinstance(join.this, exp.Table)
    )
    physical_sources: set[tuple[str, str]] = set()
    for table_node in table_nodes:
        # Derived tables and nested scopes cannot be safely mapped by this
        # conservative root-scope implementation.
        physical_matches = [
            t for t in snapshot.tables
            if t.name == table_node.name
            and (not table_node.db or t.namespace == table_node.db)
        ]
        if len(physical_matches) != 1:
            continue
        meta = physical_matches[0]
        source_identity = (meta.namespace, meta.name)
        if source_identity in physical_sources:
            return  # Self-join occurrences cannot share one physical filter target.
        physical_sources.add(source_identity)
        table_lookup[table_node.alias_or_name] = meta
        table_lookup.setdefault(table_node.name, meta)

    # Group date comparisons by column
    date_candidates: dict[tuple[str, str, str], dict[str, Any]] = {}
    category_added = False

    for idx, c in enumerate(conjuncts):
        # 1. Equality predicate (category candidate)
        if isinstance(c, exp.EQ) and not category_added:
            col_node = c.left if isinstance(c.left, exp.Column) else (c.right if isinstance(c.right, exp.Column) else None)
            lit_node = c.right if isinstance(c.right, (exp.Literal, exp.Boolean)) else (c.left if isinstance(c.left, (exp.Literal, exp.Boolean)) else None)
            if col_node and lit_node:
                col_name = col_node.name
                table_meta = _resolve_column_table(col_node, table_lookup, snapshot)
                if table_meta:
                    col_meta = next((cm for cm in table_meta.columns if cm.name == col_name), None)
                    if col_meta and col_meta.canonical_type in ("string", "integer", "float", "boolean"):
                        if isinstance(lit_node, exp.Boolean) and col_meta.canonical_type != "boolean":
                            continue
                        if col_meta.canonical_type == "boolean" and not isinstance(lit_node, exp.Boolean):
                            continue  # String-to-boolean coercion differs across source engines.
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
                                    db_type=col_meta.db_type,
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
                table_meta = _resolve_column_table(col_node, table_lookup, snapshot)
                if table_meta:
                    col_meta = next((cm for cm in table_meta.columns if cm.name == col_name), None)
                    if col_meta and col_meta.canonical_type in ("date", "datetime"):
                        op_name = ">=" if isinstance(c, exp.GTE) else (">" if isinstance(c, exp.GT) else ("<=" if isinstance(c, exp.LTE) else "<"))
                        key = (table_meta.namespace, table_meta.name, col_name)
                        entry = date_candidates.setdefault(key, {
                            "col_meta": col_meta,
                            "table_meta": table_meta,
                            "ops": {},
                        })
                        if len(lit_node.this) != 10:
                            continue
                        if op_name in entry["ops"]:
                            entry["ops"]["duplicate"] = True
                        entry["ops"][op_name] = (idx, lit_node.this)

    # Process date candidates into date_range parameters
    for identity, info in date_candidates.items():
        ops = info["ops"]
        col_meta = info["col_meta"]
        table_meta = info["table_meta"]
        col_name = col_meta.name

        start_date: str | None = None
        end_date_inclusive: str | None = None
        start_idx: int | None = None
        end_idx: int | None = None

        # Only a pre-existing inclusive lower bound and exclusive upper bound
        # have the exact semantics required by the date range contract.
        if ">=" in ops:
            start_idx, start_date = ops[">="]

        if "<" in ops:
            end_idx, raw_end = ops["<"]
            # Exclusive end: subtract 1 day for inclusive UI end
            try:
                excl_d = dt.date.fromisoformat(raw_end[:10])
                end_date_inclusive = (excl_d - dt.timedelta(days=1)).isoformat()
            except ValueError:
                end_date_inclusive = raw_end[:10]

        if len(ops) != 2:
            continue
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
                        db_type=col_meta.db_type,
                        operator="date_range",
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


def _resolve_column_table(
    column: exp.Column,
    aliases: dict[str, Any],
    snapshot: CatalogSnapshot,
) -> Any | None:
    if column.table:
        return aliases.get(column.table)
    scoped_tables = list({(table.namespace, table.name): table for table in aliases.values()}.values())
    matches = [
        table for table in scoped_tables
        if any(col.name == column.name for col in table.columns)
    ]
    return matches[0] if len(matches) == 1 else None


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

    verify_parameter_definitions(
        definitions,
        extract_eligible_parameters(template_sql, snapshot, engine, author_limit, max_rows),
    )
    allowed_keys = {key for definition in definitions for key in (definition.name, definition.slot_id)}
    if set(values) - allowed_keys:
        raise ParameterCompilationError("Unknown parameter name")
    if len({definition.slot_id for definition in definitions}) != len(definitions):
        raise ParameterCompilationError("Duplicate parameter slot")
    if sum(definition.param_type == "category" for definition in definitions) > 1:
        raise ParameterCompilationError("Only one category selector is supported")

    effective_max_rows = min(max_rows, get_settings().max_max_rows)
    if author_limit is not None and author_limit > 0:
        effective_max_rows = min(effective_max_rows, author_limit)
    bound_parameters: list[BoundParameter] = []
    resolved_dates: list[ResolvedDateRange] = []
    supplied_values: dict[str, Any] = {}

    for param_def in definitions:
        # Resolve value from input or default
        if param_def.name != param_def.slot_id and param_def.name in values and param_def.slot_id in values:
            raise ParameterCompilationError(f"Parameter {param_def.name} was supplied more than once")
        if param_def.name in values:
            val = values[param_def.name]
        elif param_def.slot_id in values:
            val = values[param_def.slot_id]
        else:
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
            _verify_physical_target(param_def.target, param_def.source_type, snapshot)

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
                BoundParameter(
                    name=placeholder_name, scalar_type=param_def.source_type,
                    value=Decimal(str(val)) if param_def.source_type == "decimal" else float(val) if param_def.source_type == "float" else val,
                )
            )

            # Install placeholder in AST
            _install_category_placeholder(ast, param_def.target, placeholder_name, snapshot)

        elif param_def.param_type == "date_range":
            if param_def.target is None:
                raise ParameterCompilationError(f"Date range parameter {param_def.name} missing target")
            _verify_physical_target(param_def.target, param_def.source_type, snapshot)

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
            _install_date_range_placeholders(ast, param_def.target, p_start, p_end, snapshot)

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


def _install_category_placeholder(
    ast: exp.Expression, target: ParameterTarget, placeholder_name: str, snapshot: CatalogSnapshot
) -> None:
    where = ast.args.get("where") if isinstance(ast, exp.Select) else None
    if where is None:
        raise ParameterCompilationError("Category target has no root WHERE clause")
    try:
        index = int(target.predicate_path.removeprefix("where."))
        predicate = _conjuncts(where.this)[index]
    except (ValueError, IndexError):
        raise ParameterCompilationError("Category target path no longer matches template")
    if not isinstance(predicate, exp.EQ):
        raise ParameterCompilationError("Category target must identify an equality predicate")
    col_node = predicate.left if isinstance(predicate.left, exp.Column) else (predicate.right if isinstance(predicate.right, exp.Column) else None)
    value_node = predicate.right if col_node is predicate.left else predicate.left
    if col_node is None or not isinstance(value_node, (exp.Literal, exp.Boolean)):
        raise ParameterCompilationError("Category target must identify a literal equality predicate")
    if col_node.name != target.column_name:
        raise ParameterCompilationError("Category target path does not match target column")
    _verify_predicate_scope(ast, col_node, target, snapshot)
    if col_node is predicate.left:
        predicate.set("expression", exp.Placeholder(this=placeholder_name))
    else:
        predicate.set("this", exp.Placeholder(this=placeholder_name))


def _verify_physical_target(target: ParameterTarget, source_type: str, snapshot: CatalogSnapshot) -> None:
    tables = [t for t in snapshot.tables
              if t.namespace == target.namespace
              and t.name == target.table_name]
    if len(tables) != 1:
        raise ParameterCompilationError("Parameter target physical table is missing or ambiguous")
    columns = [c for c in tables[0].columns if c.name == target.column_name]
    if len(columns) != 1:
        raise ParameterCompilationError("Parameter target physical column is missing or ambiguous")
    column = columns[0]
    if column.canonical_type != source_type or (target.db_type and column.db_type != target.db_type):
        raise ParameterCompilationError("Parameter target physical type changed")


def verify_parameter_definitions(
    proposed: tuple[ParameterDefinition, ...],
    discovered: list[ParameterDefinition],
) -> None:
    """Permit author metadata while keeping slot identity and AST targets server owned."""
    if len({item.slot_id for item in proposed}) != len(proposed) or len({item.name for item in proposed}) != len(proposed):
        raise ParameterCompilationError("Duplicate parameter slot or name")
    candidates = {item.slot_id: item for item in discovered}
    category_count = 0
    for item in proposed:
        candidate = candidates.get(item.slot_id)
        if candidate is None or item.param_type != candidate.param_type or item.source_type != candidate.source_type:
            raise ParameterCompilationError("Parameter slot was not discovered for this query")
        if item.param_type != "result_count" and item.target != candidate.target:
            raise ParameterCompilationError("Parameter target differs from the server-discovered predicate")
        if item.param_type == "category":
            category_count += 1
        if item.param_type == "result_count" and item.default_value is None:
            raise ParameterCompilationError("Result count requires a valid default")
    if category_count > 1:
        raise ParameterCompilationError("Only one category selector is supported")


def _install_date_range_placeholders(
    ast: exp.Expression,
    target: ParameterTarget,
    p_start: str,
    p_end: str,
    snapshot: CatalogSnapshot,
) -> None:
    where = ast.args.get("where")
    if where is None:
        raise ParameterCompilationError("Date range target has no WHERE clause")
    conjuncts = _conjuncts(where.this)
    try:
        start_index = int(target.predicate_path.removeprefix("where."))
        end_index = int((target.secondary_predicate_path or "").removeprefix("where."))
        start_node, end_node = conjuncts[start_index], conjuncts[end_index]
    except (ValueError, IndexError):
        raise ParameterCompilationError("Date range target path no longer matches template")
    if not isinstance(start_node, exp.GTE) or not isinstance(end_node, exp.LT):
        raise ParameterCompilationError("Date ranges require >= start and < exclusive end predicates")
    for node in (start_node, end_node):
        col = node.left if isinstance(node.left, exp.Column) else None
        if col is None or col.name != target.column_name:
            raise ParameterCompilationError("Date range target path does not match target column")
        # Snapshot is verified before placeholder installation, and the AST
        # predicate must still resolve through the exact root source.
        _verify_predicate_scope(ast, col, target, snapshot)
    start_node.set("expression", exp.Placeholder(this=p_start))
    end_node.set("expression", exp.Placeholder(this=p_end))


def _conjuncts(node: exp.Expression) -> list[exp.Expression]:
    if isinstance(node, exp.And):
        return _conjuncts(cast(exp.Expression, node.left)) + _conjuncts(cast(exp.Expression, node.right))
    return [node]


def _verify_predicate_scope(
    ast: exp.Expression, column: exp.Column, target: ParameterTarget, snapshot: CatalogSnapshot
) -> None:
    if not isinstance(ast, exp.Select):
        raise ParameterCompilationError("Parameter target requires a root SELECT")
    from_node = ast.args.get("from_")
    tables = [from_node.this] if from_node and isinstance(from_node.this, exp.Table) else []
    tables.extend(join.this for join in ast.args.get("joins", []) if isinstance(join.this, exp.Table))
    if column.table:
        matches = [
            table for table in tables
            if table.alias_or_name == column.table
            and table.name == target.table_name
            and (not table.db or table.db == target.namespace)
        ]
    else:
        matches = []
        for source in tables:
            physical = [meta for meta in snapshot.tables if meta.name == source.name
                        and (not source.db or meta.namespace == source.db)]
            if len(physical) == 1 and any(meta.name == target.column_name for meta in physical[0].columns):
                if physical[0].name == target.table_name and physical[0].namespace == target.namespace:
                    matches.append(source)
    if len(matches) != 1:
        raise ParameterCompilationError("Parameter target scope does not match physical table")
