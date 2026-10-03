"""Public agent ids, approved domains, widget conversations and messages."""

import sqlalchemy as sa

from alembic import op

revision = "0003_widget_sessions"
down_revision = "0002_security_hardening"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "agents",
        sa.Column(
            "public_id",
            sa.String(64),
            nullable=False,
            server_default=sa.text("'agt_' || replace(gen_random_uuid()::text, '-', '')"),
        ),
    )
    op.create_unique_constraint("uq_agents_public_id", "agents", ["public_id"])
    op.add_column("agents", sa.Column("published_at", sa.DateTime(timezone=True), nullable=True))

    op.create_table(
        "domains",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "tenant_id",
            sa.String(36),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("hostname", sa.String(255), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("tenant_id", "hostname"),
    )
    op.create_table(
        "conversations",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "tenant_id",
            sa.String(36),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "agent_id",
            sa.String(36),
            sa.ForeignKey("agents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("channel", sa.String(20), nullable=False),
        sa.Column("origin", sa.String(255), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_table(
        "messages",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "tenant_id",
            sa.String(36),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "conversation_id",
            sa.String(36),
            sa.ForeignKey("conversations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("role", sa.String(20), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    for table in ("domains", "conversations", "messages"):
        op.create_index(f"ix_{table}_tenant_id", table, ["tenant_id"])
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY tenant_isolation_{table} ON {table} "
            "USING (tenant_id = current_setting('app.tenant_id', true)) "
            "WITH CHECK (tenant_id = current_setting('app.tenant_id', true))"
        )
    op.create_index("ix_messages_conversation_id", "messages", ["conversation_id"])

    # Public (no-login) lookup: resolve a published agent and its verified origins by public id.
    # SECURITY DEFINER so the visitor path never needs broad table access.
    op.execute(
        """
        CREATE FUNCTION public_resolve_agent(p_public_id text) RETURNS json
        LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public
        AS $$
            SELECT json_build_object(
                'agent_id', a.id,
                'tenant_id', a.tenant_id,
                'name', a.name,
                'hostnames', COALESCE(
                    (SELECT json_agg(d.hostname) FROM domains d
                     WHERE d.tenant_id = a.tenant_id AND d.status = 'verified'),
                    '[]'::json)
            )
            FROM agents a
            WHERE a.public_id = p_public_id AND a.status = 'published'
        $$;
        """
    )
    op.execute("REVOKE ALL ON FUNCTION public_resolve_agent(text) FROM PUBLIC")
    op.execute("GRANT EXECUTE ON FUNCTION public_resolve_agent(text) TO concierge_app")
    op.execute("GRANT SELECT, INSERT, UPDATE ON domains, conversations TO concierge_app")
    op.execute("GRANT SELECT, INSERT ON messages TO concierge_app")


def downgrade() -> None:
    op.execute("DROP FUNCTION IF EXISTS public_resolve_agent(text)")
    for table in ("messages", "conversations", "domains"):
        op.drop_table(table)
    op.drop_constraint("uq_agents_public_id", "agents", type_="unique")
    op.drop_column("agents", "published_at")
    op.drop_column("agents", "public_id")
