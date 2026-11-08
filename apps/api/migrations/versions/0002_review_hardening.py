"""Connection policy revisions and durable query explanation metadata."""

from alembic import op
import sqlalchemy as sa

revision = "0002_review_hardening"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("connections", sa.Column("policy_version", sa.Integer(), nullable=False, server_default="1"))
    op.add_column("query_runs", sa.Column("assumptions", sa.Text(), nullable=False, server_default="[]"))
    op.add_column("query_runs", sa.Column("warnings", sa.Text(), nullable=False, server_default="[]"))
    op.add_column("query_runs", sa.Column("canonical_sql", sa.Text(), nullable=True))
    op.add_column("query_runs", sa.Column("truncated", sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade() -> None:
    for column in ("truncated", "canonical_sql", "warnings", "assumptions"):
        op.drop_column("query_runs", column)
    op.drop_column("connections", "policy_version")
