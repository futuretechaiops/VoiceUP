"""Row-level security, runtime role, append-only audit log and invitations.

Design (see docs/adr/0003-database-roles-and-rls.md):
* ``concierge_app`` is the runtime role: not a superuser, owns nothing, no BYPASSRLS.
* Every request transaction sets ``app.tenant_id`` (and ``app.user_id`` once known); with no
  tenant set, policies match nothing, so the system fails closed.
* ``audit_events`` can be inserted and read, never updated or deleted.
"""

import sqlalchemy as sa

from alembic import op

revision = "0002_security_hardening"
down_revision = "0001_foundation"
branch_labels = None
depends_on = None

TENANT_TABLES = ("memberships", "agents", "audit_events", "invitations")


def upgrade() -> None:
    op.create_table(
        "invitations",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "tenant_id",
            sa.String(36),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("email", sa.String(320), nullable=False),
        sa.Column("role", sa.Enum(name="role", create_type=False), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("invited_by", sa.String(36), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_invitations_tenant_id", "invitations", ["tenant_id"])

    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'concierge_app') THEN
                CREATE ROLE concierge_app NOLOGIN NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE;
            END IF;
        END
        $$;
        """
    )

    for table in TENANT_TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY tenant_isolation_{table} ON {table} "
            "USING (tenant_id = current_setting('app.tenant_id', true)) "
            "WITH CHECK (tenant_id = current_setting('app.tenant_id', true))"
        )

    # A user may read their own memberships across tenants; this is how the tenant is resolved
    # from verified identity before any tenant context exists.
    op.execute(
        "CREATE POLICY own_memberships ON memberships FOR SELECT "
        "USING (user_id = current_setting('app.user_id', true))"
    )

    # tenants: readable only for the current tenant. Not FORCEd for the owning role.
    op.execute("ALTER TABLE tenants ENABLE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_read ON tenants FOR SELECT "
        "USING (id = current_setting('app.tenant_id', true))"
    )

    # users: readable when it is the caller, or a member of the current tenant.
    # (The memberships sub-select is itself row-level secured.)
    op.execute("ALTER TABLE users ENABLE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY user_read ON users FOR SELECT "
        "USING (id = current_setting('app.user_id', true) "
        "OR id IN (SELECT user_id FROM memberships "
        "WHERE tenant_id = current_setting('app.tenant_id', true)))"
    )

    # Authentication bootstrap: map an identity subject to a user id without exposing users.
    op.execute(
        """
        CREATE FUNCTION auth_resolve_user(subject text) RETURNS text
        LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public
        AS $$ SELECT id FROM users WHERE identity_subject = subject $$;
        """
    )
    op.execute("REVOKE ALL ON FUNCTION auth_resolve_user(text) FROM PUBLIC")
    op.execute("GRANT EXECUTE ON FUNCTION auth_resolve_user(text) TO concierge_app")

    # Append-only audit log: privilege and trigger (the trigger also binds the table owner).
    op.execute(
        """
        CREATE FUNCTION audit_events_immutable() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'audit_events is append-only';
        END
        $$;
        """
    )
    op.execute(
        "CREATE TRIGGER audit_events_no_change BEFORE UPDATE OR DELETE ON audit_events "
        "FOR EACH ROW EXECUTE FUNCTION audit_events_immutable()"
    )
    op.execute(
        "CREATE TRIGGER audit_events_no_truncate BEFORE TRUNCATE ON audit_events "
        "FOR EACH STATEMENT EXECUTE FUNCTION audit_events_immutable()"
    )

    op.execute("GRANT USAGE ON SCHEMA public TO concierge_app")
    op.execute("GRANT SELECT ON tenants, users TO concierge_app")
    op.execute("GRANT SELECT, INSERT, UPDATE ON memberships, agents, invitations TO concierge_app")
    op.execute("GRANT SELECT, INSERT ON audit_events TO concierge_app")


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS audit_events_no_truncate ON audit_events")
    op.execute("DROP TRIGGER IF EXISTS audit_events_no_change ON audit_events")
    op.execute("DROP FUNCTION IF EXISTS audit_events_immutable()")
    op.execute("DROP FUNCTION IF EXISTS auth_resolve_user(text)")
    op.execute("DROP POLICY IF EXISTS user_read ON users")
    op.execute("ALTER TABLE users DISABLE ROW LEVEL SECURITY")
    op.execute("DROP POLICY IF EXISTS tenant_read ON tenants")
    op.execute("ALTER TABLE tenants DISABLE ROW LEVEL SECURITY")
    op.execute("DROP POLICY IF EXISTS own_memberships ON memberships")
    for table in TENANT_TABLES:
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation_{table} ON {table}")
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")
    op.drop_table("invitations")
