"""Knowledge base: ingest crawled pages and retrieve evidence with PostgreSQL full-text search.

Full-text search (stemming, ranked) is used instead of embeddings: no external embedding service
is needed, retrieval is deterministic and testable, and a single company website is small. The
spec's pgvector retrieval can be added later behind ``retrieve`` without changing callers.
"""

import re
from collections.abc import Iterable
from dataclasses import dataclass

from sqlalchemy import delete, select, text
from sqlalchemy.orm import Session

from .chunking import checksum, chunk_blocks
from .crawler import CrawledPage
from .models import KnowledgeChunk, KnowledgeDocument, KnowledgeSource, utcnow

STOPWORDS = frozenset(
    """a about after all also am an and any are as at be been being but by can could did do does
    for from get give had has have he her here him his how i if in into is it its just like me
    more most my no not of on one or our out over please she should so some such than that the
    their them then there these they this to too up us was we were what when where which who whom
    why will with would you your tell know want need""".split()
)  # fmt: skip


@dataclass
class CrawlStats:
    pages: int = 0
    changed: int = 0
    unchanged: int = 0
    chunks: int = 0
    removed: int = 0


@dataclass
class Retrieved:
    chunk_id: str
    text: str
    url: str
    title: str
    score: float


def get_or_create_source(db: Session, tenant_id: str, url: str) -> KnowledgeSource:
    source = db.scalar(
        select(KnowledgeSource).where(
            KnowledgeSource.tenant_id == tenant_id, KnowledgeSource.url == url
        )
    )
    if source is None:
        source = KnowledgeSource(tenant_id=tenant_id, url=url)
        db.add(source)
        db.flush()
    return source


def ingest_pages(
    db: Session, tenant_id: str, source: KnowledgeSource, pages: Iterable[CrawledPage]
) -> CrawlStats:
    stats = CrawlStats()
    seen_urls: set[str] = set()
    seen_blocks: set[str] = set()  # sitewide boilerplate (footer, address) is indexed only once
    source.status = "crawling"
    db.commit()
    for page in pages:
        seen_urls.add(page.url)
        stats.pages += 1
        blocks = []
        for body, is_heading in page.extracted.blocks:
            key = " ".join(body.split())
            if not is_heading and len(key) >= 20:
                if key in seen_blocks:
                    continue
                seen_blocks.add(key)
            blocks.append((body, is_heading))
        chunks = chunk_blocks(page.title, blocks)
        digest = checksum("\n".join(chunks))
        doc = db.scalar(
            select(KnowledgeDocument).where(
                KnowledgeDocument.tenant_id == tenant_id, KnowledgeDocument.url == page.url
            )
        )
        if doc is not None and doc.checksum == digest and doc.status == "indexed":
            stats.unchanged += 1
            doc.fetched_at = utcnow()
            db.commit()
            continue
        if doc is None:
            doc = KnowledgeDocument(
                tenant_id=tenant_id, source_id=source.id, url=page.url, title=page.title[:500],
                checksum=digest,
            )  # fmt: skip
            db.add(doc)
        else:
            db.execute(delete(KnowledgeChunk).where(KnowledgeChunk.document_id == doc.id))
            doc.title = page.title[:500]
            doc.checksum = digest
            doc.content_version += 1
            doc.status = "indexed"
            doc.fetched_at = utcnow()
        db.flush()
        digests = {checksum(c): c for c in chunks}
        existing = set(
            db.scalars(
                select(KnowledgeChunk.checksum).where(
                    KnowledgeChunk.tenant_id == tenant_id,
                    KnowledgeChunk.checksum.in_(list(digests)),
                )
            )
        )
        for ordinal, (digest_c, body) in enumerate(digests.items()):
            if digest_c in existing:  # identical text already indexed (shared header/footer)
                continue
            db.add(
                KnowledgeChunk(
                    tenant_id=tenant_id,
                    document_id=doc.id,
                    ordinal=ordinal,
                    text=body,
                    checksum=digest_c,
                )  # fmt: skip
            )
            stats.chunks += 1
        stats.changed += 1
        db.commit()

    stale = list(
        db.scalars(
            select(KnowledgeDocument).where(
                KnowledgeDocument.tenant_id == tenant_id,
                KnowledgeDocument.source_id == source.id,
                KnowledgeDocument.url.not_in(seen_urls or {""}),
            )
        )
    )
    for doc in stale:
        db.delete(doc)  # cascades to its chunks: deleted pages leave no searchable text
        stats.removed += 1
    source.status = "ready"
    source.page_count = stats.pages
    source.last_crawled_at = utcnow()
    source.last_error = None
    db.commit()
    return stats


def keywords(query: str, limit: int = 12) -> list[str]:
    tokens = re.findall(r"[a-z0-9]+", query.lower())
    out: list[str] = []
    for token in tokens:
        if len(token) >= 2 and token not in STOPWORDS and token not in out:
            out.append(token)
    return out[:limit]


SYNONYMS = {
    "cost": ["price", "pricing", "fee"],
    "price": ["pricing", "cost", "fee"],
    "fees": ["fee", "pricing", "price"],
    "much": [],
    "call": ["phone", "contact"],
    "email": ["contact"],
}


def retrieve(db: Session, tenant_id: str, query: str, k: int = 5) -> list[Retrieved]:
    """Rank chunks by how many distinct query terms they cover, then by ts_rank_cd density."""
    terms = keywords(query)
    if not terms:
        return []
    groups = [[t, *SYNONYMS.get(t, [])] for t in terms]
    params: dict[str, object] = {"t": tenant_id, "k": k}
    cover_parts = []
    for i, group in enumerate(groups):
        params[f"g{i}"] = " | ".join(group)
        cover_parts.append(f"(c.tsv @@ to_tsquery('english', :g{i}))::int")
    params["q"] = " | ".join(w for g in groups for w in g)
    cover = " + ".join(cover_parts)
    rows = db.execute(
        text(
            f"""
            SELECT c.id, c.text, d.url, d.title,
                   ({cover}) AS covered,
                   ts_rank_cd(c.tsv, to_tsquery('english', :q), 32) AS score
            FROM knowledge_chunks c
            JOIN knowledge_documents d ON d.id = c.document_id
            WHERE c.tenant_id = :t AND d.tenant_id = :t AND d.status = 'indexed'
              AND c.tsv @@ to_tsquery('english', :q)
            ORDER BY covered DESC, score DESC, c.ordinal
            LIMIT :k
            """  # noqa: S608 - only bound parameters are interpolated into the cover expression
        ),
        params,
    ).all()
    return [Retrieved(r.id, r.text, r.url, r.title, float(r.score)) for r in rows]
