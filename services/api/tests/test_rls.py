"""Database-level isolation, exercised as the unprivileged runtime role."""

import pytest
from conftest import A_ADMIN, A_TENANT, B_TENANT
from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import DBAPIError, ProgrammingError

TENANT_TABLES = ["memberships", "agents", "audit_events", "invitations"]


def scoped(engine: Engine, tenant: str | None, user: str | None = None):  # type: ignore[no-untyped-def]
    conn = engine.connect()
    tx = conn.begin()
    if tenant:
        conn.execute(text("SELECT set_config('app.tenant_id', :v, true)"), {"v": tenant})
    if user:
        conn.execute(text("SELECT set_config('app.user_id', :v, true)"), {"v": user})
    return conn, tx


def add_agent(owner: Engine, tenant: str, name: str) -> None:
    with owner.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO agents VALUES (gen_random_uuid()::text, :t, :n, 'r', 'objective', "
                "'draft', now(), now())"
            ),
            {"t": tenant, "n": name},
        )


def test_runtime_role_is_unprivileged(app_engine: Engine) -> None:
    with app_engine.connect() as conn:
        row = conn.execute(
            text("SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname = current_user")
        ).one()
        assert row == (False, False)
        owned = conn.execute(
            text(
                "SELECT count(*) FROM pg_tables "
                "WHERE schemaname='public' AND tableowner=current_user"
            )
        ).scalar()
        assert owned == 0


@pytest.mark.parametrize("table", TENANT_TABLES)
def test_no_tenant_context_sees_nothing(seeded: Engine, app_engine: Engine, table: str) -> None:
    add_agent(seeded, A_TENANT, "Ava")
    conn, tx = scoped(app_engine, None)
    try:
        assert conn.execute(text(f"SELECT count(*) FROM {table}")).scalar() == 0
    finally:
        tx.rollback()
        conn.close()


def test_tenant_sees_only_own_rows(seeded: Engine, app_engine: Engine) -> None:
    add_agent(seeded, A_TENANT, "Ava")
    add_agent(seeded, B_TENANT, "Ben")
    conn, tx = scoped(app_engine, A_TENANT)
    try:
        names = conn.execute(text("SELECT name FROM agents")).scalars().all()
        assert names == ["Ava"]
    finally:
        tx.rollback()
        conn.close()


def test_cannot_write_into_another_tenant(app_engine: Engine) -> None:
    conn, tx = scoped(app_engine, A_TENANT)
    try:
        with pytest.raises(DBAPIError):
            conn.execute(
                text(
                    "INSERT INTO agents VALUES (gen_random_uuid()::text, :t, 'x', 'r', 'o', "
                    "'draft', now(), now())"
                ),
                {"t": B_TENANT},
            )
    finally:
        tx.rollback()
        conn.close()


def test_cannot_update_or_delete_another_tenants_rows(seeded: Engine, app_engine: Engine) -> None:
    add_agent(seeded, B_TENANT, "Ben")
    conn, tx = scoped(app_engine, A_TENANT)
    try:
        assert conn.execute(text("UPDATE agents SET name='hacked'")).rowcount == 0
    finally:
        tx.rollback()
        conn.close()
    with seeded.connect() as conn2:
        assert conn2.execute(text("SELECT name FROM agents")).scalars().all() == ["Ben"]


def test_runtime_role_cannot_delete_agents(seeded: Engine, app_engine: Engine) -> None:
    add_agent(seeded, A_TENANT, "Ava")
    conn, tx = scoped(app_engine, A_TENANT)
    try:
        with pytest.raises(ProgrammingError):  # DELETE is not granted (least privilege)
            conn.execute(text("DELETE FROM agents"))
    finally:
        tx.rollback()
        conn.close()


def test_users_are_not_enumerable_across_tenants(app_engine: Engine) -> None:
    conn, tx = scoped(app_engine, B_TENANT)
    try:
        emails = set(conn.execute(text("SELECT email FROM users")).scalars())
        assert "a@example.test" not in emails
        assert "b@example.test" in emails
    finally:
        tx.rollback()
        conn.close()


def test_audit_log_is_append_only_for_runtime_role(app_engine: Engine) -> None:
    conn, tx = scoped(app_engine, A_TENANT)
    try:
        conn.execute(
            text(
                "INSERT INTO audit_events VALUES (gen_random_uuid()::text, :t, :u, 'x', 'y', "
                "gen_random_uuid()::text, 'success', now())"
            ),
            {"t": A_TENANT, "u": A_ADMIN},
        )
        with pytest.raises(ProgrammingError):  # permission denied: privilege revoked
            conn.execute(text("UPDATE audit_events SET action='tampered'"))
    finally:
        tx.rollback()
        conn.close()


def test_audit_log_is_append_only_even_for_the_owner(seeded: Engine) -> None:
    with seeded.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO audit_events VALUES (gen_random_uuid()::text, :t, :u, 'x', 'y', "
                "gen_random_uuid()::text, 'success', now())"
            ),
            {"t": A_TENANT, "u": A_ADMIN},
        )
    with pytest.raises(DBAPIError, match="append-only"), seeded.begin() as conn:
        conn.execute(text("DELETE FROM audit_events"))
