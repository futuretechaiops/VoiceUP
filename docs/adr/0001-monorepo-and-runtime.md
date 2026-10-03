# ADR 0001: Monorepo and application runtime

- Status: Accepted
- Date: 2026-10-03

## Decision

Use an npm workspace monorepo for the Next.js dashboard and standalone TypeScript widget, with a separately packaged Python/FastAPI service. Deploy stateless application services as containers. Use PostgreSQL as the system of record and pgvector for initial semantic retrieval.

## Consequences

Shared contracts can be generated from OpenAPI, while frontend and backend release boundaries remain explicit. The team maintains two language toolchains, justified by the strong web ecosystem in TypeScript and AI/data ecosystem in Python.

