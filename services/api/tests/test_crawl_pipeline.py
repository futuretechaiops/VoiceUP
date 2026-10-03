"""Netguard, extraction, chunking, crawler (static and JavaScript-rendered) and retrieval."""

import pytest
from conftest import A_TENANT, B_TENANT
from sitefixture import serve
from sqlalchemy import text
from sqlalchemy.engine import Engine

from concierge.chunking import chunk_blocks
from concierge.crawler import SiteCrawler, normalise
from concierge.db import SessionLocal, bind_context
from concierge.extract import extract
from concierge.knowledge import get_or_create_source, ingest_pages, keywords, retrieve
from concierge.netguard import UnsafeUrl, validate_url


# ---- netguard -------------------------------------------------------------------------------
@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1/", "http://169.254.169.254/latest/meta-data/", "http://10.0.0.5/",
        "http://[::1]/", "ftp://example.com/", "file:///etc/passwd", "https://user:pw@example.com/",
        "https://evil.example/", "https://example.com:8443/",
    ],
)  # fmt: skip
def test_unsafe_urls_are_blocked(url: str) -> None:
    allowed = {"127.0.0.1", "169.254.169.254", "10.0.0.5", "::1", "example.com"}
    with pytest.raises(UnsafeUrl):
        validate_url(url, allowed)


def test_public_ip_literal_on_allow_list_is_fine_and_private_needs_override() -> None:
    assert validate_url("https://93.184.216.34/", {"93.184.216.34"})
    assert validate_url("http://127.0.0.1:8080/", {"127.0.0.1"}, allow_private=True)


def test_normalise_drops_fragments_queries_and_binary_files() -> None:
    assert normalise("/services/?tab=1#top", "https://Acme.test/") == "https://acme.test/services"
    assert normalise("https://acme.test/brochure.pdf") is None
    assert normalise("mailto:a@b.c") is None
    assert normalise("javascript:alert(1)") is None


# ---- extraction and chunking ----------------------------------------------------------------
HTML = """<html><head><title>Acme | Home</title><meta name="description" content="Blue widgets made in Yorkshire."></head>
<body><nav><a href="/x">Menu item</a></nav><header><div>Header banner text here</div></header>
<main><h1>Welcome</h1><div><p>We repair <strong>widgets</strong> quickly.</p></div><script>evil()</script>
<a href="tel:+4400">Call</a><a href="mailto:hi@acme.test?subject=x">Mail</a></main>
<footer><p>Acme Ltd, Leeds</p></footer></body></html>"""


def test_extract_keeps_content_and_contacts_but_drops_nav_and_scripts() -> None:
    page = extract(HTML)
    assert page.title == "Acme | Home"
    body = page.text
    assert "We repair widgets quickly." in body
    assert "Blue widgets made in Yorkshire." in body
    assert "Phone: +4400" in body and "Email: hi@acme.test" in body
    assert "Acme Ltd, Leeds" in body  # footer kept
    assert "Menu item" not in body and "evil()" not in body


def test_chunks_carry_title_and_section_and_respect_size() -> None:
    blocks = [
        ("Pricing", True),
        ("Repairs start from forty pounds and bulk supply is quoted. " * 30, False),
    ]
    chunks = chunk_blocks("Our services", blocks)
    assert len(chunks) >= 2
    assert all(c.startswith("Our services > Pricing\n") for c in chunks)
    assert all(len(c) < 1200 for c in chunks)


def test_keywords_drop_stopwords() -> None:
    assert keywords("What are your tenant fees?") == ["tenant", "fees"]


# ---- crawler --------------------------------------------------------------------------------
def crawl(url: str, **kw):  # type: ignore[no-untyped-def]
    kw.setdefault("mode", "http")  # the static fixture pages are short; auto would go to a browser
    crawler = SiteCrawler(url, allow_private=True, delay=0, **kw)
    return crawler, list(crawler.crawl())


def test_static_crawl_follows_site_links_and_respects_boundaries() -> None:
    with serve() as base:
        crawler, pages = crawl(base)
    urls = {p.url.removeprefix(base) for p in pages}
    assert urls >= {"/", "/about", "/services", "/contact", "/loop"}
    assert "/private" not in urls  # robots.txt
    assert not any("evil" in u for u in urls)  # external host, direct and via redirect
    assert not any(u.endswith(".pdf") for u in urls)
    reasons = " ".join(r for _, r in crawler.skipped)
    assert "robots.txt" in reasons and "unsafe" in reasons
    assert len(urls) <= 6  # the ?page= loop collapses to a single URL


def test_max_pages_is_enforced() -> None:
    with serve() as base:
        _, pages = crawl(base, max_pages=2)
    assert len(pages) == 2


def test_javascript_rendered_site_is_crawled_with_the_browser() -> None:
    pytest.importorskip("playwright")
    with serve(spa=True) as base:
        _, pages = crawl(base, mode="auto")
    by_path = {p.url.removeprefix(base): p for p in pages}
    assert {"/", "/pricing", "/team"} <= set(by_path)  # sub-pages found via rendered links
    assert "two hundred pounds a month" in by_path["/pricing"].extracted.text


def test_static_only_mode_sees_nothing_on_a_spa() -> None:
    with serve(spa=True) as base:
        _, pages = crawl(base, mode="http")
    assert all("two hundred pounds" not in p.extracted.text for p in pages)


# ---- ingest and retrieve --------------------------------------------------------------------
def ingest(tenant: str, base: str, pages) -> object:  # type: ignore[no-untyped-def]
    with SessionLocal() as db:
        bind_context(db, tenant_id=tenant)
        source = get_or_create_source(db, tenant, base + "/")
        db.commit()
        return ingest_pages(db, tenant, source, iter(pages))


def test_ingest_search_isolation_dedupe_and_recrawl(seeded: Engine) -> None:
    with serve() as base:
        _, pages = crawl(base)
        stats = ingest(A_TENANT, base, pages)
        again = ingest(A_TENANT, base, pages)
    assert stats.pages == len(pages) and stats.chunks > 0  # type: ignore[attr-defined]
    assert again.changed == 0 and again.unchanged == len(pages)  # type: ignore[attr-defined]

    with SessionLocal() as db:
        bind_context(db, tenant_id=A_TENANT)
        hits = retrieve(db, A_TENANT, "how much do widget repairs cost?")
        assert any("forty pounds" in h.text and h.url.endswith("/services") for h in hits[:3])
        phone = retrieve(db, A_TENANT, "what is your phone number")
        assert any("0113" in h.text or "441130000000" in h.text for h in phone)
        # the shared footer is stored once, not once per page
        footer = db.execute(
            text("SELECT count(*) FROM knowledge_chunks WHERE text LIKE '%1 High Street%'")
        ).scalar()
        assert footer == 1

    with SessionLocal() as db:  # tenant B sees nothing of tenant A
        bind_context(db, tenant_id=B_TENANT)
        assert retrieve(db, B_TENANT, "widget repairs cost") == []
        assert retrieve(db, A_TENANT, "widget repairs cost") == []  # even asking for A's id


def test_changed_and_deleted_pages_are_reflected(seeded: Engine) -> None:
    with serve() as base:
        _, pages = crawl(base)
        ingest(A_TENANT, base, pages)
        # page edited, and /about removed from the next crawl
        edited = [p for p in pages if not p.url.endswith("/about")]
        for p in edited:
            if p.url.endswith("/services"):
                p.extracted.blocks.append(
                    ("Emergency repairs are now available on Sundays too.", False)
                )
        stats = ingest(A_TENANT, base, edited)
    assert stats.removed == 1 and stats.changed >= 1  # type: ignore[attr-defined]
    with SessionLocal() as db:
        bind_context(db, tenant_id=A_TENANT)
        assert retrieve(db, A_TENANT, "ISO 9001 certification") == []  # deleted page is gone
        assert retrieve(db, A_TENANT, "emergency repairs Sundays")
