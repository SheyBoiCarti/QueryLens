"""Immutable, bounded analytics metadata. These models never contain source rows.

Binding compilation and driver dispatch belong to the SQL/execution layer.
"""

from __future__ import annotations

import datetime as dt
import math
from collections.abc import Callable, Mapping
from decimal import Decimal, InvalidOperation
from types import MappingProxyType
from typing import Annotated, Any, Literal, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    ValidationInfo,
    field_serializer,
    field_validator,
    model_validator,
)

from querylens.config import get_settings
from querylens.domain.schema import CanonicalType

RunOrigin = Literal["natural_language", "follow_up", "manual_sql", "saved_question"]
Identifier = Annotated[str, Field(min_length=1, max_length=255)]
Version = Annotated[int, Field(ge=1)]
Scalar = str | int | float | bool
DriverScalar = str | int | float | bool | dt.datetime | dt.date | Decimal


class FrozenMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True, allow_inf_nan=False)


class ObjectReference(FrozenMetadata):
    namespace: Identifier
    table_name: Identifier
    column_name: Identifier | None = None
    canonical_type: CanonicalType | None = None
    db_type: Annotated[str, Field(min_length=1, max_length=255)] | None = None

    @model_validator(mode="after")
    def column_signature(self) -> Self:
        if self.column_name is not None and (self.canonical_type is None or self.db_type is None):
            raise ValueError("Column references require canonical and physical types")
        return self


class MetricReference(FrozenMetadata):
    id: Annotated[str, Field(min_length=1, max_length=36)]
    key: Annotated[str, Field(min_length=1, max_length=100)]
    version: Version
    dsl_hash: Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]


class LabelReference(FrozenMetadata):
    namespace: Identifier
    table_name: Identifier
    column_name: Identifier | None = None
    display_name: Annotated[str, Field(min_length=1, max_length=200)]
    description: Annotated[str, Field(max_length=2000)] | None = None
    version: Version


class AppliedFilter(FrozenMetadata):
    slot_id: Annotated[str, Field(min_length=1, max_length=100)]
    column: ObjectReference
    operator: Literal["=", "!=", "<>", "<", "<=", ">", ">=", "IN", "BETWEEN", "date_range"]
    value: Scalar | Annotated[tuple[Scalar, ...], Field(max_length=100)]


def _freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item) for item in value)
    return value


def _thaw(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _thaw(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw(item) for item in value]
    return value


class BoundParameter(FrozenMetadata):
    name: Annotated[str, Field(pattern=r"^[A-Za-z_][A-Za-z0-9_]{0,99}$")]
    scalar_type: CanonicalType
    value: DriverScalar

    @model_validator(mode="before")
    @classmethod
    def restore_json_scalar(cls, data: Any, info: ValidationInfo) -> Any:
        # JSON lacks date/Decimal types. The explicit tag preserves them exactly.
        if info.mode == "json" and isinstance(data, dict) and isinstance(data.get("value"), str):
            parsers: dict[str, Callable[[str], DriverScalar]] = {
                "date": dt.date.fromisoformat,
                "datetime": dt.datetime.fromisoformat,
                "decimal": Decimal,
            }
            scalar_type = data.get("scalar_type")
            parser = parsers.get(scalar_type) if isinstance(scalar_type, str) else None
            if parser:
                try:
                    data = {**data, "value": parser(data["value"])}
                except (ValueError, InvalidOperation) as exc:
                    raise ValueError("Invalid typed binding scalar") from exc
        return data

    @model_validator(mode="after")
    def scalar_matches_tag(self) -> Self:
        expected = {
            "string": str,
            "integer": int,
            "float": float,
            "boolean": bool,
            "date": dt.date,
            "datetime": dt.datetime,
            "decimal": Decimal,
        }
        if type(self.value) is not expected[self.scalar_type]:
            raise ValueError("Binding value must match its scalar_type exactly")
        if isinstance(self.value, Decimal) and not self.value.is_finite():
            raise ValueError("Binding values must be finite")
        if isinstance(self.value, float) and not math.isfinite(self.value):
            raise ValueError("Binding values must be finite")
        return self


class ResolvedDateRange(FrozenMetadata):
    slot_id: Annotated[str, Field(min_length=1, max_length=100)]
    start: dt.datetime | dt.date
    end_exclusive: dt.datetime | dt.date

    @model_validator(mode="after")
    def matching_boundaries(self) -> Self:
        if type(self.start) is not type(self.end_exclusive):
            raise ValueError("Date boundaries must share a type")
        try:
            if self.start >= self.end_exclusive:
                raise ValueError("Date boundaries must have increasing values")
        except TypeError as exc:
            raise ValueError("Date boundaries must share timezone awareness") from exc
        return self


class ResolvedParameters(FrozenMetadata):
    bindings: Annotated[tuple[BoundParameter, ...], Field(max_length=100)] = ()
    values: Mapping[str, JsonValue] = Field(default_factory=lambda: MappingProxyType({}))
    resolved_dates: Annotated[tuple[ResolvedDateRange, ...], Field(max_length=100)] = ()
    max_rows: Annotated[int, Field(ge=1, le=1000)] = 100

    @field_validator("values", mode="after")
    @classmethod
    def freeze_values(cls, values: Mapping[str, JsonValue]) -> Mapping[str, JsonValue]:
        if len(values) > 100 or any(not key or len(key) > 100 for key in values):
            raise ValueError("Parameter values exceed budget")
        return _freeze(values)

    @field_serializer("values")
    def serialize_values(self, values: Mapping[str, JsonValue]) -> dict[str, JsonValue]:
        return _thaw(values)

    @model_validator(mode="after")
    def bounded(self) -> Self:
        if len(self.model_dump_json().encode("utf-8")) > get_settings().max_request_bytes:
            raise ValueError("Resolved parameters exceed request byte budget")
        if len({binding.name for binding in self.bindings}) != len(self.bindings):
            raise ValueError("Duplicate binding names")
        return self


class RunContext(FrozenMetadata):
    effective_question: Annotated[str, Field(min_length=1, max_length=4000)]
    canonical_sql_template: Annotated[str, Field(min_length=1, max_length=32768)]
    author_limit: Annotated[int, Field(ge=0)] | None = None
    applied_filters: Annotated[tuple[AppliedFilter, ...], Field(max_length=100)] = ()
    metric_references: Annotated[tuple[MetricReference, ...], Field(max_length=100)] = ()
    label_references: Annotated[tuple[LabelReference, ...], Field(max_length=200)] = ()
    referenced_objects: Annotated[tuple[ObjectReference, ...], Field(max_length=200)] = ()
    snapshot_hash: Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
    policy_version: Version
    semantic_version: Version
    resolved_parameters: ResolvedParameters | None = None

    @model_validator(mode="after")
    def bounded_context(self) -> Self:
        settings = get_settings()
        if len(self.effective_question) > settings.max_question_chars:
            raise ValueError("Effective question exceeds configured budget")
        if len(self.canonical_sql_template.encode("utf-8")) > settings.max_sql_bytes:
            raise ValueError("SQL template exceeds configured byte budget")
        # The existing context estimator counts UTF-8 bytes as tokens.
        if len(self.model_dump_json().encode("utf-8")) > min(settings.max_request_bytes, settings.max_input_tokens):
            raise ValueError("Run context exceeds configured context/request byte budget")
        return self
