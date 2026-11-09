"""Semantic drift and dependency validation for saved questions (Contract C09)."""

from __future__ import annotations

import json
from typing import Any

from querylens.domain.schema import CatalogSnapshot
from querylens.semantics.versions import SemanticContext


class SavedQuestionReviewRequired(Exception):
    """Raised when physical schema or referenced metrics drifted since saved question revision."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


def validate_saved_dependencies(
    definition: dict[str, Any],
    snapshot: CatalogSnapshot,
    semantics: SemanticContext,
) -> None:
    """Validate that physical referenced objects and metrics remain compatible with the saved definition."""
    # 1. Physical objects check
    ref_objects_raw = definition.get("referenced_objects_json")
    if ref_objects_raw:
        try:
            ref_objects = json.loads(ref_objects_raw) if isinstance(ref_objects_raw, str) else ref_objects_raw
        except Exception:
            ref_objects = []

        table_map = {(t.namespace, t.name): t for t in snapshot.tables}

        for obj in ref_objects:
            t_name = obj.get("table_name", "")
            namespace = obj.get("namespace", "")
            table = table_map.get((namespace, t_name))
            if table is None:
                raise SavedQuestionReviewRequired(f"Referenced table '{obj.get('table_name')}' no longer exists")

            col_name = obj.get("column_name")
            if col_name:
                col = next((c for c in table.columns if c.name == col_name), None)
                if col is None:
                    raise SavedQuestionReviewRequired(f"Referenced column '{col_name}' no longer exists")
                expected_type = obj.get("canonical_type")
                if expected_type and col.canonical_type != expected_type:
                    raise SavedQuestionReviewRequired(
                        f"Referenced column '{col_name}' type changed from {expected_type} to {col.canonical_type}"
                    )
                expected_db_type = obj.get("db_type")
                if expected_db_type and col.db_type != expected_db_type:
                    raise SavedQuestionReviewRequired(
                        f"Referenced column '{col_name}' physical type changed from {expected_db_type} to {col.db_type}"
                    )

    # 2. Parameter targets check
    param_defs_raw = definition.get("parameter_definitions_json")
    if param_defs_raw:
        try:
            param_defs = json.loads(param_defs_raw) if isinstance(param_defs_raw, str) else param_defs_raw
        except Exception:
            param_defs = []

        table_map = {(t.namespace, t.name): t for t in snapshot.tables}
        for p in param_defs:
            target = p.get("target")
            if target:
                t_name = target.get("table_name", "")
                namespace = target.get("namespace", "")
                table = table_map.get((namespace, t_name))
                if table is None:
                    raise SavedQuestionReviewRequired(f"Parameter target table '{target.get('table_name')}' no longer exists")
                c_name = target.get("column_name", "")
                col = next((c for c in table.columns if c.name == c_name), None)
                if col is None:
                    raise SavedQuestionReviewRequired(f"Parameter target column '{target.get('column_name')}' no longer exists")
                expected_type = p.get("source_type")
                if expected_type and col.canonical_type != expected_type:
                    raise SavedQuestionReviewRequired(
                        f"Parameter target column '{c_name}' type changed from {expected_type} to {col.canonical_type}"
                    )
                expected_db_type = target.get("db_type") or p.get("source_db_type")
                if expected_db_type and col.db_type != expected_db_type:
                    raise SavedQuestionReviewRequired(
                        f"Parameter target column '{c_name}' physical type changed from {expected_db_type} to {col.db_type}"
                    )

    # 3. Metric references check
    ref_metrics_raw = definition.get("metric_references_json")
    if ref_metrics_raw:
        try:
            ref_metrics = json.loads(ref_metrics_raw) if isinstance(ref_metrics_raw, str) else ref_metrics_raw
        except Exception:
            ref_metrics = []

        enabled_metrics = {m.id: m for m in semantics.metrics if m.enabled}

        for m_ref in ref_metrics:
            m_id = m_ref.get("id")
            if m_id not in enabled_metrics:
                raise SavedQuestionReviewRequired(f"Referenced metric '{m_ref.get('key')}' is disabled or removed")
            current_metric = enabled_metrics[m_id]
            if current_metric.version != m_ref.get("version") or current_metric.dsl.compute_hash() != m_ref.get("dsl_hash"):
                raise SavedQuestionReviewRequired(f"Referenced metric '{m_ref.get('key')}' has changed definition")
