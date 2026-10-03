"""Initial tenancy and agent foundation.

Note: the v0.1.0 version of this file failed on a clean database because the ``role`` enum was
created twice. It had never been applied to a shared environment, so it was corrected in place
(see docs/adr/0003-database-roles-and-rls.md).
"""

import sqlalchemy as sa

from alembic import op

revision = "0001_foundation"
down_revision = None
branch_labels = None
depends_on = None

ROLE_VALUES = ("platform_admin", "customer_admin", "sales_manager", "sales_agent", "analyst")


def upgrade() -> None:
    # pgvector is not used until WP3 (knowledge ingestion), whose migration must require it.
    # Tolerate its absence here so the tenancy slice can be verified on plain PostgreSQL.
    op.execute(
        """
        DO $$
        BEGIN
            CREATE EXTENSION IF NOT EXISTS vector;
        EXCEPTION WHEN undefined_file OR feature_not_supported THEN
            RAISE NOTICE 'pgvector is not installed; required from WP3 onwards';
        END
        $$;
        """
    )
    op.create_table(
        "tenants",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "users",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("identity_subject", sa.String(255), nullable=False, unique=True),
        sa.Column("email", sa.String(320), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    role = sa.Enum(*ROLE_VALUES, name="role")
    op.create_table(
        "memberships",
        sa.Column(
            "tenant_id",
            sa.String(36),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("role", role, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("tenant_id", "user_id"),
    )
    op.create_table(
        "agents",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "tenant_id",
            sa.String(36),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("role_description", sa.String(200), nullable=False),
        sa.Column("primary_objective", sa.Text(), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("tenant_id", "name"),
    )
    op.create_table(
        "audit_events",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("actor_user_id", sa.String(36), nullable=False),
        sa.Column("action", sa.String(120), nullable=False),
        sa.Column("target_type", sa.String(80), nullable=False),
        sa.Column("target_id", sa.String(36), nullable=False),
        sa.Column("outcome", sa.String(30), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    for table in ("memberships", "agents", "audit_events"):
        op.create_index(f"ix_{table}_tenant_id", table, ["tenant_id"])


def downgrade() -> None:
    op.drop_table("audit_events")
    op.drop_table("agents")
    op.drop_table("memberships")
    op.drop_table("users")
    op.drop_table("tenants")
    sa.Enum(name="role").drop(op.get_bind(), checkfirst=True)
