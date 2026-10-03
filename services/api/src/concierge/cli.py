"""Operator commands. Run from the repo root, e.g.:  python -m concierge.cli bootstrap-tenant ...

* ``bootstrap-tenant``  create a company, a published assistant and its approved website(s).
                        Uses the OWNER connection (MIGRATION_DATABASE_URL). Operator-verified:
                        the person running it is vouching for the domains.
* ``crawl``             build or refresh the knowledge base from the company's website.
* ``outbox-send``       deliver any pending notification emails now (also runs automatically).
* ``ask``               test retrieval from the terminal.
* ``seed-demo``         local demo company with a few built-in pages (development only).
"""

import argparse
import sys
import uuid

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from .config import get_settings
from .origins import normalise_hostname

NAMESPACE = uuid.UUID("6f1d4c9e-2b7a-4d1e-9a52-0c5e8f3b7a10")
DEMO_TENANT = "d0000000-0000-4000-8000-000000000001"
DEMO_PUBLIC_ID = "agt_demo_public"
DEMO_DOMAINS = ["localhost:8080", "127.0.0.1:8080", "localhost:5173"]

DEMO_PAGES = {
    "http://localhost:8080/lettings": (
        "Lettings at Demo Estates",
        [
            ("Lettings at Demo Estates", True),
            (
                "Our tenant fees are simple: we charge no tenant fees beyond the refundable "
                "holding deposit of one week's rent and the security deposit of five weeks' rent.",
                False,
            ),
            (
                "Viewings can be booked Monday to Saturday between 9am and 6pm. Bring photo ID "
                "to your viewing and we can start referencing the same day.",
                False,
            ),
        ],
    ),
    "http://localhost:8080/areas": (
        "Areas we cover",
        [
            ("Areas we cover", True),
            (
                "Demo Estates covers Manchester city centre, Salford Quays, Chorlton and the "
                "Northern Quarter, with offices on Deansgate and in Didsbury.",
                False,
            ),
            ("Phone: 0161 000 0000", False),
        ],
    ),
}


def _owner_engine() -> Engine:
    settings = get_settings()
    return create_engine(settings.migration_database_url or settings.database_url)


def bootstrap_tenant(args: argparse.Namespace) -> None:
    site_host = normalise_hostname(args.site.split("//")[-1].split("/")[0])
    bare = site_host.removeprefix("www.")
    hosts = sorted({bare, f"www.{bare}", *[normalise_hostname(h) for h in args.extra_domain]})
    tenant_id = str(uuid.uuid5(NAMESPACE, args.name.lower()))
    agent_id = str(uuid.uuid5(NAMESPACE, f"agent:{tenant_id}:{args.agent_name.lower()}"))
    with _owner_engine().begin() as conn:
        conn.execute(
            text(
                "INSERT INTO tenants (id,name,status,notify_email,created_at) "
                "VALUES (:t,:n,'active',:e,now()) "
                "ON CONFLICT (id) DO UPDATE SET notify_email = EXCLUDED.notify_email"
            ),
            {"t": tenant_id, "n": args.name, "e": args.notify_email},
        )
        conn.execute(
            text(
                "INSERT INTO agents (id,tenant_id,name,role_description,primary_objective,status,"
                "published_at,created_at,updated_at) VALUES (:a,:t,:an,'Website assistant',"
                "'Answer questions about the company and take enquiries',"
                "'published',now(),now(),now()) "
                "ON CONFLICT (id) DO NOTHING"
            ),
            {"a": agent_id, "t": tenant_id, "an": args.agent_name},
        )
        for host in hosts:
            conn.execute(
                text(
                    "INSERT INTO domains (id,tenant_id,hostname,status,created_at) "
                    "VALUES (gen_random_uuid()::text,:t,:h,'verified',now()) "
                    "ON CONFLICT (tenant_id,hostname) DO NOTHING"
                ),
                {"t": tenant_id, "h": host},
            )
        public_id: str = conn.execute(
            text("SELECT public_id FROM agents WHERE id=:a"), {"a": agent_id}
        ).scalar_one()
    print("Tenant ready.")
    print(f"  Tenant id       : {tenant_id}")
    print(f"  Public agent id : {public_id}")
    print(f"  Approved sites  : {', '.join(hosts)}")
    print(f"  Leads emailed to: {args.notify_email}")
    print("\nNext: crawl the website, then add the script tag to the site:")
    print(f"  python -m concierge.cli crawl --tenant-id {tenant_id} --site {args.site}")


def crawl(args: argparse.Namespace) -> None:
    from .crawler import SiteCrawler
    from .db import SessionLocal, bind_context
    from .knowledge import get_or_create_source, ingest_pages

    settings = get_settings()
    if args.allow_private and settings.app_env in {"staging", "production"}:
        sys.exit("--allow-private is for local testing only.")
    crawler = SiteCrawler(
        args.site, max_pages=args.max_pages, delay=args.delay, mode=args.mode,
        allow_private=args.allow_private,
    )  # fmt: skip
    with SessionLocal() as db:
        bind_context(db, tenant_id=args.tenant_id)
        source = get_or_create_source(db, args.tenant_id, crawler.start)
        db.commit()
        try:
            stats = ingest_pages(db, args.tenant_id, source, crawler.crawl())
        except Exception as exc:
            db.rollback()
            source.status = "failed"
            source.last_error = f"{type(exc).__name__}: {exc}"[:500]
            db.commit()
            raise
    print(
        f"Crawled {stats.pages} pages: {stats.changed} new or changed, "
        f"{stats.unchanged} unchanged, {stats.chunks} chunks added, {stats.removed} removed."
    )
    for url, reason in crawler.skipped[:20]:
        print(f"  skipped {url}: {reason}")
    if stats.pages == 0:
        sys.exit("No pages were indexed. Check the URL, robots.txt and network access.")


def outbox_send(_: argparse.Namespace) -> None:
    from .db import SessionLocal
    from .mailer import get_mailer
    from .outbox import process_outbox

    print(f"Sent {process_outbox(SessionLocal, get_mailer())} email(s).")


def ask(args: argparse.Namespace) -> None:
    from .db import SessionLocal, bind_context
    from .knowledge import retrieve

    with SessionLocal() as db:
        bind_context(db, tenant_id=args.tenant_id)
        results = retrieve(db, args.tenant_id, args.question)
    if not results:
        print("No matching evidence.")
    for r in results:
        print(f"[{r.score:.2f}] {r.title} ({r.url})\n    {r.text[:200]!r}")


def seed_demo(_: argparse.Namespace) -> None:
    from .chunking import chunk_blocks  # noqa: F401
    from .crawler import CrawledPage
    from .db import SessionLocal, bind_context
    from .extract import Extracted
    from .knowledge import get_or_create_source, ingest_pages

    settings = get_settings()
    if settings.app_env in {"staging", "production"}:
        sys.exit("Refusing to seed demo data in staging or production.")
    user, membership, agent = (
        "d0000000-0000-4000-8000-000000000002",
        "d0000000-0000-4000-8000-000000000003",
        "d0000000-0000-4000-8000-000000000004",
    )
    with _owner_engine().begin() as conn:
        conn.execute(
            text(
                "INSERT INTO tenants (id,name,status,notify_email,created_at) "
                "VALUES (:t,'Demo Estates Ltd','active',NULL,now()) ON CONFLICT (id) DO NOTHING"
            ),
            {"t": DEMO_TENANT},
        )
        conn.execute(
            text(
                "INSERT INTO users VALUES (:u,'demo-admin','admin@demo-estates.example',now()) "
                "ON CONFLICT (id) DO NOTHING"
            ),
            {"u": user},
        )
        conn.execute(
            text(
                "INSERT INTO memberships (tenant_id,id,user_id,role,created_at) "
                "VALUES (:t,:m,:u,'customer_admin',now()) ON CONFLICT (id) DO NOTHING"
            ),
            {"t": DEMO_TENANT, "m": membership, "u": user},
        )
        conn.execute(
            text(
                "INSERT INTO agents (id,tenant_id,name,role_description,primary_objective,"
                "status,public_id,published_at,created_at,updated_at) "
                "VALUES (:a,:t,'Ava','Sales concierge',"
                "'Answer questions and capture qualified enquiries',"
                "'published',:p,now(),now(),now()) ON CONFLICT (id) DO NOTHING"
            ),
            {"a": agent, "t": DEMO_TENANT, "p": DEMO_PUBLIC_ID},
        )
        for host in DEMO_DOMAINS:
            conn.execute(
                text(
                    "INSERT INTO domains (id,tenant_id,hostname,status,created_at) "
                    "VALUES (gen_random_uuid()::text,:t,:h,'verified',now()) "
                    "ON CONFLICT (tenant_id,hostname) DO NOTHING"
                ),
                {"t": DEMO_TENANT, "h": host},
            )
    pages = [
        CrawledPage(url=u, title=title, extracted=Extracted(title=title, blocks=blocks))
        for u, (title, blocks) in DEMO_PAGES.items()
    ]
    with SessionLocal() as db:
        bind_context(db, tenant_id=DEMO_TENANT)
        source = get_or_create_source(db, DEMO_TENANT, "http://localhost:8080/")
        db.commit()
        ingest_pages(db, DEMO_TENANT, source, iter(pages))
    print("Demo data ready.")
    print(f"  Public agent id : {DEMO_PUBLIC_ID}")
    print(f"  Approved sites  : {', '.join(DEMO_DOMAINS)}")
    print("  Try asking: 'What are your tenant fees?'  or  'Which areas do you cover?'")


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m concierge.cli")
    sub = parser.add_subparsers(dest="command", required=True)

    b = sub.add_parser("bootstrap-tenant", help="create company, assistant and approved domains")
    b.add_argument("--name", required=True)
    b.add_argument("--site", required=True, help="https://www.example.com")
    b.add_argument("--notify-email", required=True)
    b.add_argument("--agent-name", default="Ava")
    b.add_argument("--extra-domain", action="append", default=[])
    b.set_defaults(func=bootstrap_tenant)

    c = sub.add_parser("crawl", help="build or refresh the knowledge base from the website")
    c.add_argument("--tenant-id", required=True)
    c.add_argument("--site", required=True)
    c.add_argument("--max-pages", type=int, default=200)
    c.add_argument("--delay", type=float, default=0.5)
    c.add_argument("--mode", choices=["auto", "http", "browser"], default="auto")
    c.add_argument("--allow-private", action="store_true", help="local testing only")
    c.set_defaults(func=crawl)

    sub.add_parser("outbox-send", help="deliver pending emails now").set_defaults(func=outbox_send)

    a = sub.add_parser("ask", help="test retrieval")
    a.add_argument("--tenant-id", required=True)
    a.add_argument("question")
    a.set_defaults(func=ask)

    sub.add_parser("seed-demo", help="local demo data").set_defaults(func=seed_demo)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
