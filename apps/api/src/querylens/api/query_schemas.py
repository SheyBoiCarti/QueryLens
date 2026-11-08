"""Discriminated public query response contracts shared through OpenAPI."""

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field
from querylens.domain.schema import CanonicalType
from querylens.domain.analytics import RunContext, RunOrigin
from querylens.domain.presentation import PresentationMetadata
from querylens.sql.parameters import ParameterDefinition


class PublicRunBase(BaseModel):
    model_config = ConfigDict(extra="forbid")
    query_id: str
    connection_id: str
    state_version: int
    question: str
    created_at: str
    updated_at: str
    origin: RunOrigin = "natural_language"
    parent_query_id: str | None = None
    source_query_id: str | None = None
    saved_question_id: str | None = None
    saved_question_version: int | None = None


class PublicColumn(BaseModel):
    name: str
    type: CanonicalType
    db_type: str


class PublicRunCompleted(PublicRunBase):
    status: Literal["completed"]
    dialect: Literal["postgresql", "mysql"]
    sql: str
    assumptions: list[str]
    warnings: list[str]
    columns: list[PublicColumn]
    row_count: int
    truncated: bool
    results_available: bool
    rows: list[dict[str, str | float | bool | None]] | None = None
    context: RunContext | None = None
    presentation: PresentationMetadata | None = None
    results_expires_at: str | None = None


class PublicRunClarification(PublicRunBase):
    status: Literal["clarification_required"]
    clarification_question: str


class PublicRunFailed(PublicRunBase):
    status: Literal["failed", "rejected", "interrupted"]
    error_code: str
    safe_message: str


class PublicRunCancelled(PublicRunBase):
    status: Literal["cancelled"]
    safe_message: str


class PublicRunPending(PublicRunBase):
    status: Literal["queued", "contextualizing", "generating", "validating", "executing", "repairing", "cancelling"]


PublicRun = Annotated[
    PublicRunCompleted | PublicRunClarification | PublicRunFailed | PublicRunCancelled | PublicRunPending,
    Field(discriminator="status"),
]


class ParameterDiscoveryResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    template_fingerprint: str
    definitions: list[ParameterDefinition]


class SavedQuestionCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_query_id: str
    title: Annotated[str, Field(min_length=1, max_length=200)]
    description: Annotated[str, Field(max_length=2000)] | None = None
    parameters: list[ParameterDefinition] = []
    chart_preference: Annotated[str, Field(max_length=50)] | None = None


class SavedQuestionUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision: int
    title: Annotated[str, Field(min_length=1, max_length=200)] | None = None
    description: Annotated[str, Field(max_length=2000)] | None = None
    parameters: list[ParameterDefinition] | None = None
    chart_preference: Annotated[str, Field(max_length=50)] | None = None
    replacement_query_id: str | None = None


class SavedQuestionDuplicateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: Annotated[str, Field(min_length=1, max_length=200)]


class SavedQuestionRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    parameters: dict[str, Any] = {}
    expected_revision: int | None = None


class SavedQuestionSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    connection_id: str
    title: str
    description: str | None = None
    chart_preference: str | None = None
    default_max_rows: int
    revision: int
    created_at: str
    updated_at: str


class SavedQuestionDetail(SavedQuestionSummary):
    canonical_sql_template: str
    effective_question: str
    parameters: list[ParameterDefinition]
    referenced_objects: list[dict[str, Any]]
    metric_references: list[dict[str, Any]]


class SavedQuestionListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    items: list[SavedQuestionSummary]
    next_cursor: str | None = None
