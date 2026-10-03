# ADR 0003: Database roles and row-level security

- Status: Accepted
- Date: 2026-10-03
- Supersedes: the enforcement details in ADR 0002

## Context

v0.1.0 claimed row-level security (RLS) isolation, but verification on PostgreSQL found three problems: the first migration failed on a clean database, the Compose setup connected as the superuser and table owner (RLS does not apply to superusers), and `POST /agents` returned 500 as an unprivileged role because the transaction-local tenant setting was lost on commit. The test suite ran on SQLite, so none of this was visible.

## Decision

- Two roles. The **owner** role runs migrations. `concierge_app` is the runtime role: not a superuser, owns nothing, no `BYPASSRLS`, and holds only the privileges migrations grant it.
- The tenant (`app.tenant_id`) and user (`app.user_id`) are applied by a SQLAlchemy `after_begin` hook on every transaction, so a commit cannot drop them. With no context the policies match nothing (fail closed).
- `memberships` has an extra read policy for the caller's own rows so that tenant can be resolved from verified identity. `users` is readable only for the caller or members of the current tenant. `auth_resolve_user(subject)` is a `SECURITY DEFINER` function that maps an identity subject to a user id.
- `audit_events` is append-only: `UPDATE` and `DELETE` are not granted to the runtime role, and a trigger blocks changes by anyone, including the owner.
- Tests run on real PostgreSQL as the runtime role. No isolation claim is accepted unless a test proves it that way.
- The shipped `0001` migration was corrected in place because it never applied successfully to any shared environment.

## Consequences

- New tenant tables must enable and force RLS, add the policy and grant privileges; a test must prove isolation.
- `DELETE` is not granted on any table yet; grant it per table when a feature needs it.
- The runtime must never be configured with the owner's credentials. Settings and docs say so.
