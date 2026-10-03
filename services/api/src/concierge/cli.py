"""Developer commands. Run from the repo root:  python -m concierge.cli seed-demo

``seed-demo`` creates a demo company, an administrator, a published agent and approved
local test domains, so the widget can be tried immediately. Uses the OWNER connection
(MIGRATION_DATABASE_URL), never the runtime role. Safe to run repeatedly.
"""

import sys

from sqlalchemy import create_engine, text

from .config import get_settings

TENANT = "d0000000-0000-4000-8000-000000000001"
USER = "d0000000-0000-4000-8000-000000000002"
MEMBERSHIP = "d0000000-0000-4000-8000-000000000003"
AGENT = "d0000000-0000-4000-8000-000000000004"
PUBLIC_ID = "agt_demo_public"
DOMAINS = ["localhost:8080", "127.0.0.1:8080", "localhost:5173"]


def seed_demo() -> None:
    settings = get_settings()
    if settings.app_env in {"staging", "production"}:
        sys.exit("Refusing to seed demo data in staging or production.")
    url = settings.migration_database_url or settings.database_url
    engine = create_engine(url)
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO tenants VALUES (:t,'Demo Estates Ltd','active',now()) "
                "ON CONFLICT (id) DO NOTHING"
            ),
            {"t": TENANT},
        )
        conn.execute(
            text(
                "INSERT INTO users VALUES (:u,'demo-admin','admin@demo-estates.example',now()) "
                "ON CONFLICT (id) DO NOTHING"
            ),
            {"u": USER},
        )
        conn.execute(
            text(
                "INSERT INTO memberships (tenant_id,id,user_id,role,created_at) "
                "VALUES (:t,:m,:u,'customer_admin',now()) ON CONFLICT (id) DO NOTHING"
            ),
            {"t": TENANT, "m": MEMBERSHIP, "u": USER},
        )
        conn.execute(
            text(
                "INSERT INTO agents (id,tenant_id,name,role_description,primary_objective,"
                "status,public_id,published_at,created_at,updated_at) "
                "VALUES (:a,:t,'Ava','Sales concierge',"
                "'Answer questions and capture qualified enquiries',"
                "'published',:p,now(),now(),now()) "
                "ON CONFLICT (id) DO NOTHING"
            ),
            {"a": AGENT, "t": TENANT, "p": PUBLIC_ID},
        )
        for host in DOMAINS:
            conn.execute(
                text(
                    "INSERT INTO domains (id,tenant_id,hostname,status,created_at) "
                    "VALUES (gen_random_uuid()::text,:t,:h,'verified',now()) "
                    "ON CONFLICT (tenant_id,hostname) DO NOTHING"
                ),
                {"t": TENANT, "h": host},
            )
    print("Demo data ready.")
    print(f"  Public agent id : {PUBLIC_ID}")
    print(f"  Approved sites  : {', '.join(DOMAINS)}")


COMMANDS = {"seed-demo": seed_demo}

if __name__ == "__main__":
    command = sys.argv[1] if len(sys.argv) > 1 else ""
    if command not in COMMANDS:
        sys.exit(f"Usage: python -m concierge.cli [{'|'.join(COMMANDS)}]")
    COMMANDS[command]()
