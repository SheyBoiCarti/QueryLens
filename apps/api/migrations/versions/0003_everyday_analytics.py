"""Everyday analytics metadata, lineage, and durable definitions.

DDL is intentionally independent of mutable application table declarations.
"""

from alembic import op
import sqlalchemy as sa

revision = "0003_everyday_analytics"
down_revision = "0002_review_hardening"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("connections", sa.Column("semantic_version", sa.Integer(), nullable=False, server_default="1"))
    # Batch mode also supports disposable SQLite development metadata.
    with op.batch_alter_table("query_runs") as batch:
        batch.add_column(sa.Column("origin", sa.String(30), nullable=False, server_default="natural_language"))
        batch.add_column(sa.Column("parent_query_id", sa.String(36), nullable=True))
        batch.add_column(sa.Column("source_query_id", sa.String(36), nullable=True))
        batch.add_column(sa.Column("saved_question_id", sa.String(36), nullable=True))
        batch.add_column(sa.Column("saved_question_version", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("submitted_sql", sa.Text(), nullable=True))
        batch.add_column(sa.Column("saved_definition_json", sa.Text(), nullable=True))
        batch.add_column(sa.Column("run_context_json", sa.Text(), nullable=True))
        batch.add_column(sa.Column("snapshot_hash", sa.String(64), nullable=True))
        batch.add_column(sa.Column("policy_version", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("semantic_version", sa.Integer(), nullable=True))
        batch.create_foreign_key("fk_query_runs_parent", "query_runs", ["parent_query_id"], ["id"], ondelete="SET NULL")
        batch.create_foreign_key("fk_query_runs_source", "query_runs", ["source_query_id"], ["id"], ondelete="SET NULL")
        batch.create_check_constraint(
            "chk_query_runs_origin", "origin IN ('natural_language', 'follow_up', 'manual_sql', 'saved_question')"
        )
        batch.create_index("idx_query_runs_parent", ["parent_query_id"])
        batch.create_index("idx_query_runs_source", ["source_query_id"])

    op.create_table(
        "catalog_labels",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("connection_id", sa.String(36), sa.ForeignKey("connections.id", ondelete="CASCADE"), nullable=False),
        sa.Column("namespace", sa.String(255), nullable=False),
        sa.Column("table_name", sa.String(255), nullable=False),
        sa.Column("column_name", sa.String(255), nullable=True),
        sa.Column("display_name", sa.String(200), nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("version", sa.Integer, nullable=False, server_default="1"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")
        ),
    )

    op.create_table(
        "saved_questions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("connection_id", sa.String(36), sa.ForeignKey("connections.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("canonical_sql_template", sa.Text, nullable=False),
        sa.Column("effective_question", sa.Text, nullable=False),
        sa.Column("parameter_definitions_json", sa.Text, nullable=False, server_default="[]"),
        sa.Column("parameter_defaults_json", sa.Text, nullable=False, server_default="{}"),
        sa.Column("default_max_rows", sa.Integer, nullable=False, server_default="100"),
        sa.Column("chart_preference", sa.String(20), nullable=True),
        sa.Column("referenced_objects_json", sa.Text, nullable=False, server_default="[]"),
        sa.Column("metric_references_json", sa.Text, nullable=False, server_default="[]"),
        sa.Column("label_references_json", sa.Text, nullable=False, server_default="[]"),
        sa.Column("snapshot_hash", sa.String(64), nullable=False),
        sa.Column("policy_version", sa.Integer, nullable=False),
        sa.Column("semantic_version", sa.Integer, nullable=False),
        sa.Column("author_limit", sa.Integer, nullable=True),
        sa.Column("revision", sa.Integer, nullable=False, server_default="1"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")
        ),
    )
    op.create_index(
        "uq_catalog_labels_table",
        "catalog_labels",
        ["connection_id", "namespace", "table_name"],
        unique=True,
        postgresql_where=sa.text("column_name IS NULL"),
        sqlite_where=sa.text("column_name IS NULL"),
    )
    op.create_index(
        "uq_catalog_labels_column",
        "catalog_labels",
        ["connection_id", "namespace", "table_name", "column_name"],
        unique=True,
        postgresql_where=sa.text("column_name IS NOT NULL"),
        sqlite_where=sa.text("column_name IS NOT NULL"),
    )
    op.create_index(
        "idx_saved_questions_owner_connection_cursor",
        "saved_questions",
        ["user_id", "connection_id", "created_at", "id"],
    )


def downgrade() -> None:
    op.drop_table("saved_questions")
    op.drop_table("catalog_labels")
    with op.batch_alter_table("query_runs") as batch:
        batch.drop_index("idx_query_runs_source")
        batch.drop_index("idx_query_runs_parent")
        batch.drop_constraint("chk_query_runs_origin", type_="check")
        batch.drop_constraint("fk_query_runs_source", type_="foreignkey")
        batch.drop_constraint("fk_query_runs_parent", type_="foreignkey")
        for name in (
            "semantic_version",
            "policy_version",
            "snapshot_hash",
            "run_context_json",
            "saved_definition_json",
            "submitted_sql",
            "saved_question_version",
            "saved_question_id",
            "source_query_id",
            "parent_query_id",
            "origin",
        ):
            batch.drop_column(name)
    op.drop_column("connections", "semantic_version")
