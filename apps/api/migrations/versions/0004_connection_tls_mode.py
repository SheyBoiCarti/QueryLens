"""Persist the provider's explicitly selected TLS verification mode."""

from alembic import op
import sqlalchemy as sa

revision = "0004_connection_tls_mode"
down_revision = "0003_everyday_analytics"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("connections", sa.Column("tls_mode", sa.String(20), nullable=False, server_default="verify-full"))


def downgrade() -> None:
    op.drop_column("connections", "tls_mode")
