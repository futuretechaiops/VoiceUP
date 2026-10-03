# ADR 0004: OIDC adapter and tenant resolution

- Status: Accepted
- Date: 2026-10-03

## Decision

Bearer tokens are verified (signature via JWKS, issuer, audience, expiry, required claims; RS256 and ES256 only). The subject maps to a user through `auth_resolve_user`. Tenant and role are read from `memberships`; claims such as `role` are ignored. A user with several memberships must send `X-Tenant-Id`, which is validated against their memberships. The provider stays behind the `TokenVerifier` interface; Cognito is the recommended default and can be swapped (WorkOS/Auth0 for enterprise SAML).

The development adapter (header-based) is refused outside development and test, and OIDC settings are mandatory when it is off.

## Not yet implemented

Invitation acceptance (creating the user and membership from an invitation token) and user provisioning on first login. They require a reviewed `SECURITY DEFINER` path and arrive in the next change.
