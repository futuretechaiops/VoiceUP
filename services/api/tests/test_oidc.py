"""OIDC adapter: tenant and role come from memberships, never from token claims alone."""

import time
from collections.abc import Iterator

import jwt
import pytest
from conftest import A_TENANT, B_TENANT
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

from concierge.auth import get_verifier
from concierge.config import get_settings
from concierge.main import app

ISSUER, AUDIENCE = "https://idp.example.test/", "voiceup-api"


class StaticVerifier:
    def __init__(self, public_key: object) -> None:
        self._key = public_key

    def verify(self, token: str) -> dict[str, object]:
        return jwt.decode(
            token,
            self._key,  # type: ignore[arg-type]
            algorithms=["RS256"],
            audience=AUDIENCE,
            issuer=ISSUER,
            options={"require": ["exp", "iat", "sub", "iss", "aud"]},
        )


@pytest.fixture(scope="module")
def keypair() -> rsa.RSAPrivateKey:
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture
def oidc_client(client: TestClient, keypair: rsa.RSAPrivateKey) -> Iterator[TestClient]:
    settings = get_settings()
    original = settings.dev_auth_enabled
    settings.dev_auth_enabled = False  # exercise the OIDC path
    app.dependency_overrides[get_verifier] = lambda: StaticVerifier(keypair.public_key())
    yield client
    app.dependency_overrides.pop(get_verifier, None)
    settings.dev_auth_enabled = original


def token(key: rsa.RSAPrivateKey, sub: str, **overrides: object) -> dict[str, str]:
    now = int(time.time())
    claims: dict[str, object] = {
        "sub": sub,
        "iss": ISSUER,
        "aud": AUDIENCE,
        "iat": now,
        "exp": now + 300,
        "role": "platform_admin",  # must be ignored
    }
    claims.update(overrides)
    return {"Authorization": f"Bearer {jwt.encode(claims, key, algorithm='RS256')}"}


def test_role_comes_from_membership_not_claims(oidc_client: TestClient, keypair) -> None:  # type: ignore[no-untyped-def]
    response = oidc_client.get("/api/v1/me", headers=token(keypair, "user-a2"))
    assert response.status_code == 200
    assert response.json()["role"] == "analyst"
    assert response.json()["tenant_id"] == A_TENANT


def test_tenant_is_server_derived(oidc_client: TestClient, keypair) -> None:  # type: ignore[no-untyped-def]
    own = oidc_client.get("/api/v1/agents", headers=token(keypair, "user-b"))
    assert own.status_code == 200


def test_multiple_memberships_require_explicit_tenant(oidc_client: TestClient, keypair) -> None:  # type: ignore[no-untyped-def]
    headers = token(keypair, "user-multi")
    assert oidc_client.get("/api/v1/me", headers=headers).status_code == 400
    chosen = oidc_client.get("/api/v1/me", headers={**headers, "X-Tenant-Id": B_TENANT})
    assert chosen.status_code == 200 and chosen.json()["role"] == "sales_agent"


def test_cannot_select_a_tenant_without_membership(oidc_client: TestClient, keypair) -> None:  # type: ignore[no-untyped-def]
    headers = {**token(keypair, "user-a"), "X-Tenant-Id": B_TENANT}
    assert oidc_client.get("/api/v1/me", headers=headers).status_code == 403


@pytest.mark.parametrize(
    "overrides",
    [{"aud": "someone-else"}, {"iss": "https://evil.example/"}, {"exp": 1}],
)
def test_bad_tokens_are_rejected(oidc_client: TestClient, keypair, overrides) -> None:  # type: ignore[no-untyped-def]
    assert (
        oidc_client.get("/api/v1/me", headers=token(keypair, "user-a", **overrides)).status_code
        == 401
    )


def test_token_signed_by_another_key_is_rejected(oidc_client: TestClient) -> None:
    other = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    assert oidc_client.get("/api/v1/me", headers=token(other, "user-a")).status_code == 401


def test_unknown_subject_is_rejected(oidc_client: TestClient, keypair) -> None:  # type: ignore[no-untyped-def]
    assert oidc_client.get("/api/v1/me", headers=token(keypair, "nobody")).status_code == 401


def test_missing_token_is_rejected(oidc_client: TestClient) -> None:
    assert oidc_client.get("/api/v1/me").status_code == 401
