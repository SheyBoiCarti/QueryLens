"""Owner-scoped catalog labels (Contracts C02, C05, C10)."""

from typing import Any
from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field

from querylens.auth.dependencies import get_current_user, verify_csrf_token
from querylens.domain.analytics import LabelReference
from querylens.schema.catalog import CatalogService
from querylens.semantics.labels import CatalogLabelInput, replace_labels
from querylens.semantics.versions import load_semantic_context

router = APIRouter(prefix="/connections/{connection_id}/labels", tags=["labels"])


class LabelsResponse(BaseModel):
    semantic_version: int
    labels: list[LabelReference]


class ReplaceLabelsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    expected_semantic_version: int = Field(ge=1)
    labels: list[CatalogLabelInput] = Field(max_length=200)


@router.get("", response_model=LabelsResponse)
def get_labels(connection_id: str, current_user: dict[str, Any] = Depends(get_current_user)) -> LabelsResponse:
    user_id = current_user["user_id"]
    snapshot = CatalogService().get_catalog(user_id, connection_id)
    semantic = load_semantic_context(user_id, snapshot)
    return LabelsResponse(semantic_version=semantic.semantic_version, labels=list(semantic.labels))


@router.put("", response_model=LabelsResponse)
def put_labels(
    connection_id: str,
    payload: ReplaceLabelsRequest,
    current_user: dict[str, Any] = Depends(get_current_user),
    _csrf: None = Depends(verify_csrf_token),
) -> LabelsResponse:
    user_id = current_user["user_id"]
    snapshot = CatalogService().get_catalog(user_id, connection_id)
    version, labels = replace_labels(user_id, snapshot, payload.expected_semantic_version, payload.labels)
    return LabelsResponse(semantic_version=version, labels=list(labels))
