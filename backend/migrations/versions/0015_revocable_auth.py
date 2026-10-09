"""Persist revocable sessions and bounded login attempt buckets."""

import sqlalchemy as sa
from alembic import op

revision = "0015_revocable_auth"
down_revision = "0014_pursuit_research_questions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "auth_sessions",
        sa.Column("token_digest", sa.String(64), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.Column("credential_fingerprint", sa.String(64), nullable=False),
    )
    op.create_index("ix_auth_sessions_expires_at", "auth_sessions", ["expires_at"])
    op.create_table(
        "auth_login_buckets",
        sa.Column("id", sa.String(72), primary_key=True),
        sa.Column("scope", sa.String(10), nullable=False),
        sa.Column("window_started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
    )
    op.create_index("ix_auth_login_buckets_scope", "auth_login_buckets", ["scope"])
    op.create_index(
        "ix_auth_login_buckets_window_started_at", "auth_login_buckets", ["window_started_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_auth_login_buckets_window_started_at", table_name="auth_login_buckets")
    op.drop_index("ix_auth_login_buckets_scope", table_name="auth_login_buckets")
    op.drop_table("auth_login_buckets")
    op.drop_index("ix_auth_sessions_expires_at", table_name="auth_sessions")
    op.drop_table("auth_sessions")
