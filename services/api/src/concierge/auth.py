"""Authentication boundary.

Tenant and role are always derived server-side. The OIDC adapter resolves them from the
``memberships`` table for the verified subject; token claims alone never grant a role.
The development adapter is for local use and tests and is refused outside development/test.
"""

from dataclasses import dataclass
from functools import lru_cache
from typing import Annotated, Protocol

import jwt
from fastapi import Depends, Header, HTTPException, status
from jwt import PyJWKClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .config import Settings, get_settings
from .db import bind_context, get_db
from .models import Membership, Role


@dataclass(frozen=True)
class Principal:
    user_id: str
    tenant_id: str
    role: Role


class TokenVerifier(Protocol):
    def verify(self, token: str) -> dict[str, object]: ...


class JwksTokenVerifier:
    """Verifies RS256/ES256 bearer tokens against the provider's JWKS."""

    def __init__(self, issuer: str, audience: str, jwks_url: str) -> None:
        self._issuer = issuer
        self._audience = audience
        self._jwks = PyJWKClient(jwks_url, cache_keys=True)

    def verify(self, token: str) -> dict[str, object]:
        key = self._jwks.get_signing_key_from_jwt(token).key
        return jwt.decode(
            token,
            key,
            algorithms=["RS256", "ES256"],
            audience=self._audience,
            issuer=self._issuer,
            options={"require": ["exp", "iat", "sub", "iss", "aud"]},
        )


@lru_cache
def _jwks_verifier(issuer: str, audience: str, jwks_url: str) -> TokenVerifier:
    return JwksTokenVerifier(issuer, audience, jwks_url)


def get_verifier() -> TokenVerifier | None:
    """None in development auth mode. Tests override this dependency."""
    s = get_settings()
    if s.dev_auth_enabled:
        return None
    assert s.oidc_issuer and s.oidc_audience and s.oidc_jwks_url  # noqa: S101 - validated
    return _jwks_verifier(s.oidc_issuer, s.oidc_audience, s.oidc_jwks_url)


def _unauthorised(detail: str) -> HTTPException:
    return HTTPException(
        status.HTTP_401_UNAUTHORIZED, detail, headers={"WWW-Authenticate": "Bearer"}
    )


def _dev_principal(
    settings: Settings,
    user_id: str | None,
    tenant_id: str | None,
    role: Role | None,
    secret: str | None,
) -> Principal:
    if secret != settings.dev_auth_secret:
        raise _unauthorised("Invalid development credentials")
    if not user_id or not tenant_id or not role:
        raise _unauthorised("Incomplete development identity")
    return Principal(user_id=user_id, tenant_id=tenant_id, role=role)


def _oidc_principal(
    db: Session,
    verifier: TokenVerifier,
    authorization: str | None,
    requested_tenant: str | None,
) -> Principal:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise _unauthorised("Missing bearer token")
    try:
        claims = verifier.verify(authorization[7:].strip())
    except jwt.PyJWTError as exc:
        raise _unauthorised("Invalid token") from exc

    subject = str(claims["sub"])
    user_id = db.scalar(select(func.auth_resolve_user(subject)))
    if user_id is None:
        raise _unauthorised("Unknown user")
    bind_context(db, user_id=user_id)

    memberships = list(db.scalars(select(Membership).where(Membership.user_id == user_id)))
    if requested_tenant:
        chosen = next((m for m in memberships if m.tenant_id == requested_tenant), None)
        if chosen is None:
            # Do not reveal whether the tenant exists.
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Not a member of this organisation")
    elif len(memberships) == 1:
        chosen = memberships[0]
    elif not memberships:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "No organisation membership")
    else:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Multiple organisations: send X-Tenant-Id")
    return Principal(user_id=user_id, tenant_id=chosen.tenant_id, role=chosen.role)


def current_principal(
    settings: Annotated[Settings, Depends(get_settings)],
    db: Annotated[Session, Depends(get_db)],
    verifier: Annotated[TokenVerifier | None, Depends(get_verifier)],
    authorization: Annotated[str | None, Header()] = None,
    x_tenant_id: Annotated[str | None, Header(alias="X-Tenant-Id")] = None,
    dev_user_id: Annotated[str | None, Header(alias="X-Dev-User-Id")] = None,
    dev_tenant_id: Annotated[str | None, Header(alias="X-Dev-Tenant-Id")] = None,
    dev_role: Annotated[Role | None, Header(alias="X-Dev-Role")] = None,
    dev_secret: Annotated[str | None, Header(alias="X-Dev-Auth-Secret")] = None,
) -> Principal:
    if settings.dev_auth_enabled:
        return _dev_principal(settings, dev_user_id, dev_tenant_id, dev_role, dev_secret)
    if verifier is None:
        raise HTTPException(status.HTTP_501_NOT_IMPLEMENTED, "OIDC adapter is not configured")
    return _oidc_principal(db, verifier, authorization, x_tenant_id)


PrincipalDep = Annotated[Principal, Depends(current_principal)]


def require_roles(*allowed: Role):  # type: ignore[no-untyped-def]
    def check(principal: PrincipalDep) -> Principal:
        if principal.role not in allowed:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Role is not permitted")
        return principal

    return check
