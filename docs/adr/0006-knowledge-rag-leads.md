# ADR 0006: Website knowledge base, grounded answers and lead email

- Status: Accepted
- Date: 2026-10-03

## Decision

- **Knowledge base:** a same-site crawler (robots.txt honoured, host allow-list, redirects revalidated, non-public IPs blocked) feeds PostgreSQL full-text search. A headless browser is used only when a page has little static text (JavaScript-built sites). Chunks carry page title and section, sitewide boilerplate is stored once, unchanged pages are skipped and removed pages are deleted.
- **Retrieval:** ranked by number of distinct query terms covered, then `ts_rank_cd`. No embedding service is needed for one company website. pgvector can be added behind `retrieve()` without changing callers.
- **Answers:** Claude receives website text in an `<evidence>` block that is declared untrusted, and must answer only from it. Without evidence there is no model call and the visitor is offered a call back. A daily cap and an extractive fallback bound cost and outages.
- **Leads:** consented form only; stored with the consent wording; emailed through a transactional outbox (same transaction as the lead, retries with backoff, dead-letter after 8 attempts). Reply-To is the visitor.
- **Demo mode:** `ADMIN_API_ENABLED=false` removes the admin API and the need for an identity provider; tenants are created by the operator CLI, which verifies domains.

## Consequences

Domain ownership is operator-asserted in demo mode; DNS verification must ship before self-service onboarding. The crawler resolves DNS before connecting, so a DNS-rebinding window remains; run it from a network without access to internal services. Voice is not implemented.
