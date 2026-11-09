"""Typed volatile answer metadata; never stored with query history."""

from typing import Annotated, Literal
from pydantic import Field
from querylens.domain.analytics import AppliedFilter, FrozenMetadata


class VerifiedDefinition(FrozenMetadata):
    id: str
    key: str
    version: int
    name: str
    description: str | None = None
    units: str | None = None


class PresentationMetadata(FrozenMetadata):
    title: str
    explanation: str
    chart_type: Literal["table", "single_value", "line", "bar"] = "table"
    x_column: str | None = None
    y_column: str | None = None
    value: str | None = None
    plot_row_order: Annotated[tuple[int, ...], Field(max_length=50)] = ()
    date_scope: tuple[AppliedFilter, ...] = ()
    verified_definitions: tuple[VerifiedDefinition, ...] = ()
    units: str | None = None
    warnings: tuple[str, ...] = ()
