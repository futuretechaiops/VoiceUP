"""Tests run against a real PostgreSQL so that row-level security is actually exercised.

Required environment (defaults match docker-compose / CI):
  TEST_OWNER_URL  superuser or table-owner connection used to create the schema and seed data
  TEST_APP_URL    connection as the unprivileged ``concierge_app`` runtime role
"""

import os
from collections.abc import Iterator
from pathlib import Path

OWNER_URL = os.environ.get(
    "TEST_OWNER_URL", "postgresql+psycopg://concierge:concierge@localhost:5432/concierge_test"
)
APP_URL = os.environ.get(
    "TEST_APP_URL", "postgresql+psycopg://concierge_app:app@localhost:5432/concierge_test"
)
os.environ.update(
    APP_ENV="test",
    DATABASE_URL=APP_URL,
    DEV_AUTH_ENABLED="true",
    DEV_AUTH_SECRET="test-secret",  # noqa: S105 - test fixture only
)

import pytest
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from alembic import command
from concierge.main import app

A_TENANT = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
B_TENANT = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
A_ADMIN = "11111111-1111-1111-1111-111111111111"
A_ANALYST = "33333333-3333-3333-3333-333333333333"
B_ADMIN = "22222222-2222-2222-2222-222222222222"
MULTI = "44444444-4444-4444-4444-444444444444"  # member of both tenants


@pytest.fixture(scope="session")
def owner_engine() -> Iterator[Engine]:
    engine = create_engine(OWNER_URL, isolation_level="AUTOCOMMIT")
    with engine.connect() as conn:
        conn.execute(text("DROP SCHEMA public CASCADE"))
        conn.execute(text("CREATE SCHEMA public"))
    cfg = Config(str(Path(__file__).parent.parent / "alembic.ini"))
    cfg.attributes["url"] = OWNER_URL
    command.upgrade(cfg, "head")
    with engine.connect() as conn:
        conn.execute(text("ALTER ROLE concierge_app LOGIN PASSWORD 'app'"))
    yield engine
    engine.dispose()


@pytest.fixture
def seeded(owner_engine: Engine) -> Engine:
    with owner_engine.connect() as conn:
        # Replica role skips the append-only triggers so tests can reset state.
        conn.execute(text("SET session_replication_role = replica"))
        conn.execute(
            text("TRUNCATE tenants, users, memberships, agents, audit_events, invitations CASCADE")
        )
        conn.execute(text("SET session_replication_role = DEFAULT"))
        conn.execute(
            text(
                "INSERT INTO tenants VALUES "
                "(:a,'Tenant A','active',now()),(:b,'Tenant B','active',now())"
            ),
            {"a": A_TENANT, "b": B_TENANT},
        )
        for uid, subject, email in [
            (A_ADMIN, "user-a", "a@example.test"),
            (A_ANALYST, "user-a2", "a2@example.test"),
            (B_ADMIN, "user-b", "b@example.test"),
            (MULTI, "user-multi", "m@example.test"),
        ]:
            conn.execute(
                text("INSERT INTO users VALUES (:i,:s,:e,now())"),
                {"i": uid, "s": subject, "e": email},
            )
        for mid, tenant, uid, role in [
            ("ma000000-0000-0000-0000-000000000001", A_TENANT, A_ADMIN, "customer_admin"),
            ("ma000000-0000-0000-0000-000000000002", A_TENANT, A_ANALYST, "analyst"),
            ("mb000000-0000-0000-0000-000000000001", B_TENANT, B_ADMIN, "customer_admin"),
            ("mm000000-0000-0000-0000-000000000001", A_TENANT, MULTI, "sales_manager"),
            ("mm000000-0000-0000-0000-000000000002", B_TENANT, MULTI, "sales_agent"),
        ]:
            conn.execute(
                text("INSERT INTO memberships VALUES (:t,:i,:u,CAST(:r AS role),now())"),
                {"t": tenant, "i": mid, "u": uid, "r": role},
            )
    return owner_engine


@pytest.fixture
def app_engine(seeded: Engine) -> Iterator[Engine]:
    engine = create_engine(APP_URL)
    yield engine
    engine.dispose()


@pytest.fixture
def client(seeded: Engine) -> Iterator[TestClient]:
    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client


def auth(tenant: str = "a", role: str = "customer_admin") -> dict[str, str]:
    ids = {"a": (A_ADMIN, A_TENANT), "b": (B_ADMIN, B_TENANT)}
    user_id, tenant_id = ids[tenant]
    return {
        "X-Dev-User-Id": user_id,
        "X-Dev-Tenant-Id": tenant_id,
        "X-Dev-Role": role,
        "X-Dev-Auth-Secret": "test-secret",
    }
