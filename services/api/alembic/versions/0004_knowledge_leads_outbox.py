"""Knowledge base, answer sources, leads and email outbox."""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0004_knowledge_leads_outbox"
down_revision = "0003_widget_sessions"
branch_labels = None
depends_on = None

NEW_TABLES = (
    "knowledge_sources",
    "knowledge_documents",
    "knowledge_chunks",
    "message_sources",
    "leads",
    "email_outbox",
)


def _tenant_col() -> sa.Column:  # type: ignore[type-arg]
    return sa.Column(
        "tenant_id", sa.String(36), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )


def upgrade() -> None:
    op.add_column("tenants", sa.Column("notify_email", sa.String(320), nullable=True))

    op.create_table(
        "knowledge_sources",
        sa.Column("id", sa.String(36), primary_key=True),
        _tenant_col(),
        sa.Column("url", sa.String(2000), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("page_count", sa.Integer, nullable=False),
        sa.Column("last_crawled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("tenant_id", "url"),
    )
    op.create_table(
        "knowledge_documents",
        sa.Column("id", sa.String(36), primary_key=True),
        _tenant_col(),
        sa.Column(
            "source_id",
            sa.String(36),
            sa.ForeignKey("knowledge_sources.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("url", sa.String(2000), nullable=False),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("checksum", sa.String(64), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("content_version", sa.Integer, nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("tenant_id", "url"),
    )
    op.create_table(
        "knowledge_chunks",
        sa.Column("id", sa.String(36), primary_key=True),
        _tenant_col(),
        sa.Column(
            "document_id",
            sa.String(36),
            sa.ForeignKey("knowledge_documents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("ordinal", sa.Integer, nullable=False),
        sa.Column("text", sa.Text, nullable=False),
        sa.Column("checksum", sa.String(64), nullable=False),
        sa.Column(
            "tsv",
            postgresql.TSVECTOR,
            sa.Computed("to_tsvector('english', text)", persisted=True),
        ),
        sa.UniqueConstraint("tenant_id", "checksum"),
    )
    op.create_index("ix_knowledge_chunks_tsv", "knowledge_chunks", ["tsv"], postgresql_using="gin")
    op.create_table(
        "message_sources",
        sa.Column("id", sa.String(36), primary_key=True),
        _tenant_col(),
        sa.Column(
            "message_id",
            sa.String(36),
            sa.ForeignKey("messages.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("chunk_id", sa.String(36), nullable=False),
        sa.Column("document_url", sa.String(2000), nullable=False),
        sa.Column("document_title", sa.String(500), nullable=False),
        sa.Column("rank", sa.Integer, nullable=False),
        sa.Column("score", sa.Float, nullable=False),
    )
    op.create_table(
        "leads",
        sa.Column("id", sa.String(36), primary_key=True),
        _tenant_col(),
        sa.Column(
            "conversation_id",
            sa.String(36),
            sa.ForeignKey("conversations.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("phone", sa.String(32), nullable=False),
        sa.Column("email", sa.String(320), nullable=False),
        sa.Column("consent_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consent_text", sa.Text, nullable=False),
        sa.Column("origin", sa.String(255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "email_outbox",
        sa.Column("id", sa.String(36), primary_key=True),
        _tenant_col(),
        sa.Column("to_address", sa.String(320), nullable=False),
        sa.Column("reply_to", sa.String(320), nullable=True),
        sa.Column("subject", sa.String(300), nullable=False),
        sa.Column("body", sa.Text, nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("attempts", sa.Integer, nullable=False),
        sa.Column("last_error", sa.Text, nullable=True),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("idempotency_key", sa.String(100), nullable=False, unique=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )

    for table in NEW_TABLES:
        op.create_index(f"ix_{table}_tenant_id", table, ["tenant_id"])
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY tenant_isolation_{table} ON {table} "
            "USING (tenant_id = current_setting('app.tenant_id', true)) "
            "WITH CHECK (tenant_id = current_setting('app.tenant_id', true))"
        )

    # The outbox worker has no tenant context; it learns which tenants have due mail through
    # this definer function (ids only), then binds each tenant in turn.
    op.execute(
        """
        CREATE FUNCTION outbox_due_tenants() RETURNS SETOF text
        LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public
        AS $$
            SELECT DISTINCT tenant_id FROM email_outbox
            WHERE status = 'pending' AND next_attempt_at <= now()
        $$;
        """
    )
    op.execute("REVOKE ALL ON FUNCTION outbox_due_tenants() FROM PUBLIC")
    op.execute("GRANT EXECUTE ON FUNCTION outbox_due_tenants() TO concierge_app")

    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON knowledge_sources TO concierge_app")
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON knowledge_documents TO concierge_app")
    op.execute("GRANT SELECT, INSERT, DELETE ON knowledge_chunks TO concierge_app")
    op.execute("GRANT SELECT, INSERT ON message_sources TO concierge_app")
    op.execute("GRANT SELECT, INSERT ON leads TO concierge_app")
    op.execute("GRANT SELECT, INSERT, UPDATE ON email_outbox TO concierge_app")


def downgrade() -> None:
    op.execute("DROP FUNCTION IF EXISTS outbox_due_tenants()")
    for table in reversed(NEW_TABLES):
        op.drop_table(table)
    op.drop_column("tenants", "notify_email")
