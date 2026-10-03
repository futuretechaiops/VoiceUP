# ADR 0002: Tenant isolation

- Status: Accepted
- Date: 2026-10-03

## Decision

Use a shared database with a mandatory `tenant_id` on tenant-owned entities. Derive tenant context from verified identity claims, apply it to every repository query, and enforce PostgreSQL row-level security as defence in depth. Cross-tenant resources return `404` to avoid revealing their existence.

## Consequences

Every new tenant-owned table and query requires an isolation test. Platform-wide administrative access must use a separately audited control path and is not implied by customer roles.

