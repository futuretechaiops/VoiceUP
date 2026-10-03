# ADR 0005: Widget sessions, origins and the placeholder responder

- Status: Accepted
- Date: 2026-10-03

## Decision

- The public agent id is not a secret. Authorisation is the browser-set `Origin` header matched, by exact host, to a **verified** domain of the agent's tenant (no implied subdomains; https only in production). Unknown, unpublished and disallowed agents all get the same generic 403, which is CORS-readable so the widget can show a clear message.
- The visitor path reads the database only through the `public_resolve_agent` SECURITY DEFINER function, then works under the resolved tenant's row-level security.
- A short-lived HS256 session token binds session, tenant, agent and origin. Rate limits are per client IP (session start) and per session (messages), in process for now and Redis-backed once the API runs on several instances.
- Domain verification by DNS is not built yet. Until WP3, an administrator may verify manually, only while `ALLOW_MANUAL_DOMAIN_VERIFICATION` is true; settings forbid that in staging and production.
- The conversation engine sits behind a `Responder` interface. The current placeholder is labelled as a test reply so nobody mistakes it for the AI; WP4 replaces it.
- The widget uses Shadow DOM, renders replies with `textContent` only, stores nothing in cookies or browser storage, and keeps the token in memory.

## Consequences

Publishing currently marks an agent live without immutable versions (WP2). A manual-verification flag must never be enabled in production. Voice, consent evidence storage and lead capture build on this session model.
