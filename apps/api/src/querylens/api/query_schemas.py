"""Discriminated public query response contracts shared through OpenAPI."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field
from querylens.domain.schema import CanonicalType
from querylens.domain.analytics import RunContext, RunOrigin
from querylens.domain.presentation import PresentationMetadata


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
