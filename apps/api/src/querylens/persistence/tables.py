"""SQLAlchemy Core table metadata definitions for QueryLens (Contract C04)."""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    UniqueConstraint,
)

metadata = MetaData()

# 1. users
users = Table(
    "users",
    metadata,
    Column("id", String(36), primary_key=True),
    Column("email", String(255), nullable=False, unique=True),
    Column("password_hash", String(255), nullable=False),
    Column("role", String(50), nullable=False, server_default="analyst"),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
)

# 2. sessions
sessions = Table(
    "sessions",
    metadata,
    Column("id", String(36), primary_key=True),
    Column("user_id", String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
    Column("token_hash", String(64), nullable=False, unique=True),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    Column("last_seen_at", DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    Column("expires_at", DateTime(timezone=True), nullable=False),
    Column("revoked_at", DateTime(timezone=True), nullable=True),
    Index("idx_sessions_user_id", "user_id"),
    Index("idx_sessions_token_hash", "token_hash"),
    Index("idx_sessions_expires_at", "expires_at"),
)

# 3. connections
connections = Table(
    "connections",
    metadata,
    Column("id", String(36), primary_key=True),
    Column("user_id", String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
    Column("name", String(100), nullable=False),
    Column("engine", String(20), nullable=False),
    Column("host", String(255), nullable=False),
    Column("port", Integer, nullable=False),
    Column("database", String(100), nullable=False),
    Column("username", String(100), nullable=False),
    Column("encrypted_password", Text, nullable=False),
    Column("tls_enabled", Boolean, nullable=False, server_default=sa.true()),
    Column("ca_cert", Text, nullable=True),
    Column("allowed_tables", Text, nullable=True),  # JSON-encoded list/map of visible tables/columns
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    CheckConstraint("engine IN ('postgresql', 'mysql')", name="chk_connections_engine"),
    Index("idx_connections_user_id", "user_id"),
)

# 4. schema_snapshots
schema_snapshots = Table(
    "schema_snapshots",
    metadata,
    Column("id", String(36), primary_key=True),
    Column("connection_id", String(36), ForeignKey("connections.id", ondelete="CASCADE"), nullable=False),
    Column("snapshot_hash", String(64), nullable=False),
    Column("policy_version", Integer, nullable=False, server_default="1"),
    Column("catalog_json", Text, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    Index("idx_snapshots_connection_hash", "connection_id", "snapshot_hash"),
)

# 5. business_metrics
business_metrics = Table(
    "business_metrics",
    metadata,
    Column("id", String(36), primary_key=True),
    Column("connection_id", String(36), ForeignKey("connections.id", ondelete="CASCADE"), nullable=False),
    Column("key", String(100), nullable=False),
    Column("name", String(200), nullable=False),
    Column("description", Text, nullable=True),
    Column("dsl_json", Text, nullable=False),
    Column("version", Integer, nullable=False, server_default="1"),
    Column("enabled", Boolean, nullable=False, server_default=sa.true()),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    UniqueConstraint("connection_id", "key", name="uq_metrics_connection_key"),
    Index("idx_metrics_connection", "connection_id"),
)

# 6. few_shot_examples
few_shot_examples = Table(
    "few_shot_examples",
    metadata,
    Column("id", String(36), primary_key=True),
    Column("connection_id", String(36), ForeignKey("connections.id", ondelete="CASCADE"), nullable=False),
    Column("dialect", String(20), nullable=False),
    Column("question", Text, nullable=False),
    Column("sql", Text, nullable=False),
    Column("assumptions", Text, nullable=True),  # JSON array of strings
    Column("verified", Boolean, nullable=False, server_default=sa.false()),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    Index("idx_few_shot_connection_dialect", "connection_id", "dialect"),
)

# 7. query_runs
query_runs = Table(
    "query_runs",
    metadata,
    Column("id", String(36), primary_key=True),
    Column("user_id", String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
    Column("connection_id", String(36), ForeignKey("connections.id", ondelete="CASCADE"), nullable=False),
    Column("status", String(50), nullable=False, server_default="queued"),
    Column("state_version", Integer, nullable=False, server_default="1"),
    Column("question", Text, nullable=False),
    Column("max_rows", Integer, nullable=False, server_default="100"),
    Column("error_code", String(100), nullable=True),
    Column("safe_message", Text, nullable=True),
    Column("clarification_question", String(500), nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    Index("idx_query_runs_user_created", "user_id", "created_at"),
    Index("idx_query_runs_connection", "connection_id"),
)

# 8. query_attempts
query_attempts = Table(
    "query_attempts",
    metadata,
    Column("id", String(36), primary_key=True),
    Column("query_run_id", String(36), ForeignKey("query_runs.id", ondelete="CASCADE"), nullable=False),
    Column("attempt_number", Integer, nullable=False),
    Column("generated_sql", Text, nullable=True),  # Nullable for model failures or clarifications
    Column("status", String(50), nullable=False),
    Column("prompt_tokens", Integer, nullable=False, server_default="0"),
    Column("completion_tokens", Integer, nullable=False, server_default="0"),
    Column("latency_ms", Integer, nullable=False, server_default="0"),
    Column("error_signature", String(100), nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    UniqueConstraint("query_run_id", "attempt_number", name="uq_query_run_attempt"),
    Index("idx_attempts_run_id", "query_run_id"),
)

# 9. evaluation_cases
evaluation_cases = Table(
    "evaluation_cases",
    metadata,
    Column("id", String(100), primary_key=True),
    Column("category", String(50), nullable=False),
    Column("dialect", String(20), nullable=False),
    Column("question", Text, nullable=False),
    Column("expected_behavior", String(50), nullable=False),  # "answerable", "ambiguous", "adversarial"
    Column("reference_sql", Text, nullable=True),
    Column("reference_result_json", Text, nullable=True),
    Column("tie_breakers", Text, nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    Index("idx_eval_cases_cat_dialect", "category", "dialect"),
)

# 10. evaluation_runs
evaluation_runs = Table(
    "evaluation_runs",
    metadata,
    Column("id", String(36), primary_key=True),
    Column("model_name", String(100), nullable=False),
    Column("engine", String(20), nullable=False),
    Column("total_cases", Integer, nullable=False),
    Column("passed_cases", Integer, nullable=False),
    Column("execution_rate", Float, nullable=False),
    Column("accuracy_rate", Float, nullable=False),
    Column("report_json", Text, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
)
