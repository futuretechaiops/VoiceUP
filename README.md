# VoiceUP: AI Sales Concierge

UK-first, multi-tenant AI sales concierge: a website widget (voice and text) that answers from approved business content, qualifies leads with deterministic scoring and books appointments. The full specification is in [docs/PROJECT_SPECIFICATION.md](docs/PROJECT_SPECIFICATION.md).

## Status: Phase A (foundation) complete

| Area | State |
| --- | --- |
| Monorepo, CI, ADRs | Done (CI: lint, types, tests on PostgreSQL, migration up/down, secret scan, CodeQL, dependency and container scans) |
| Tenancy and RBAC | Done: row-level security as an unprivileged role, fail-closed, 42 tests on real PostgreSQL |
| Identity | OIDC verification and membership-based tenant and role resolution; development adapter for local use |
| Organisations | Members list, role change (last-admin protected), invitation creation, audit events (append-only) |
| Not yet built | Invitation acceptance, agent versioning (WP2), knowledge ingestion (WP3), conversation, voice, widget logic, leads, calendars, billing |

Next work package: agent versions and publishing (WP2), then secure knowledge ingestion (WP3). The phased plan lives with the specification's section 17.

## Quick start

Requirements: Node.js 22+, Python 3.12+, Docker.

```bash
cp .env.example .env
make install
make db          # PostgreSQL (pgvector) and Valkey; creates the unprivileged runtime role
make migrate     # runs as the owner role
make dev-api     # http://localhost:8000/docs
npm run dev:dashboard
```

Run the tests (needs `make db` first; they exercise row-level security on real PostgreSQL):

```bash
make test-api && make lint-api && make typecheck
```

### Local authentication

With `DEV_AUTH_ENABLED=true` the API accepts test headers (`X-Dev-User-Id`, `X-Dev-Tenant-Id`, `X-Dev-Role`, `X-Dev-Auth-Secret`). It refuses to start that way in staging or production. Set `OIDC_ISSUER`, `OIDC_AUDIENCE` and `OIDC_JWKS_URL` and `DEV_AUTH_ENABLED=false` for real tokens.

## Rules that matter

- The API runs as `concierge_app`, never the owner. Migrations run as the owner.
- Every tenant table needs row-level security, a policy and an isolation test.
- No isolation claim without a PostgreSQL test as the runtime role.
