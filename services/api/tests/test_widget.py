"""Visitor flow: session start, origin enforcement, messages, isolation."""

import jwt
import pytest
from conftest import auth
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.engine import Engine

from concierge.config import get_settings
from concierge.widget_api import reset_limiters

SITE = "http://localhost:8080"


def make_agent(client: TestClient, tenant: str = "a", publish: bool = True) -> str:
    created = client.post(
        "/api/v1/agents",
        headers=auth(tenant),
        json={"name": f"Ava-{tenant}", "primary_objective": "Generate qualified enquiries"},
    ).json()
    if publish:
        client.post(f"/api/v1/agents/{created['id']}/publish", headers=auth(tenant))
    return created["public_id"]


def approve(client: TestClient, host: str = "localhost:8080", tenant: str = "a") -> None:
    domain = client.post("/api/v1/domains", headers=auth(tenant), json={"hostname": host}).json()
    client.post(f"/api/v1/domains/{domain['id']}/verify", headers=auth(tenant))


def start(client: TestClient, public_id: str, origin: str | None = SITE):  # type: ignore[no-untyped-def]
    headers = {"Origin": origin} if origin else {}
    return client.post(
        "/api/v1/public/widget/session", json={"agent_id": public_id}, headers=headers
    )


def test_happy_path(client: TestClient, seeded: Engine) -> None:
    public_id = make_agent(client)
    approve(client)
    response = start(client, public_id)
    assert response.status_code == 201
    assert response.headers["access-control-allow-origin"] == SITE
    body = response.json()
    assert "AI assistant" in body["notice"]

    reply = client.post(
        f"/api/v1/public/widget/session/{body['session_id']}/events",
        json={"type": "message", "text": "Do you have 2-bed flats?"},
        headers={"Authorization": f"Bearer {body['token']}", "Origin": SITE},
    )
    assert reply.status_code == 200
    assert "Do you have 2-bed flats?" in reply.json()["reply"]

    with seeded.connect() as conn:
        roles = conn.execute(text("SELECT role FROM messages ORDER BY created_at")).scalars().all()
    assert roles == ["visitor", "agent"]

    end = client.post(
        f"/api/v1/public/widget/session/{body['session_id']}/end",
        headers={"Authorization": f"Bearer {body['token']}", "Origin": SITE},
    )
    assert end.status_code == 204
    after = client.post(
        f"/api/v1/public/widget/session/{body['session_id']}/events",
        json={"type": "message", "text": "hello?"},
        headers={"Authorization": f"Bearer {body['token']}", "Origin": SITE},
    )
    assert after.status_code == 409


@pytest.mark.parametrize("origin", ["http://localhost:9999", "https://evil.example", None, "null"])
def test_unapproved_or_missing_origin_is_refused(client: TestClient, origin: str | None) -> None:
    public_id = make_agent(client)
    approve(client)
    response = start(client, public_id, origin)
    assert response.status_code == 403
    assert response.json()["title"] == "This website is not approved for this agent"


def test_unverified_domain_does_not_count(client: TestClient) -> None:
    public_id = make_agent(client)
    client.post("/api/v1/domains", headers=auth("a"), json={"hostname": "localhost:8080"})
    assert start(client, public_id).status_code == 403


def test_unpublished_and_unknown_agents_look_the_same(client: TestClient) -> None:
    draft = make_agent(client, publish=False)
    approve(client)
    a = start(client, draft)
    b = start(client, "agt_doesnotexist")
    assert a.status_code == b.status_code == 403
    assert a.json()["title"] == b.json()["title"]


def test_other_tenants_domain_does_not_authorise_this_agent(client: TestClient) -> None:
    public_id = make_agent(client, "a")
    approve(client, tenant="b")  # tenant B approves the site, not tenant A
    assert start(client, public_id).status_code == 403


def test_token_is_bound_to_session_and_origin(client: TestClient) -> None:
    public_id = make_agent(client)
    approve(client)
    approve(client, "localhost:8081")
    one = start(client, public_id).json()
    two = start(client, public_id).json()
    url = f"/api/v1/public/widget/session/{one['session_id']}/events"
    body = {"type": "message", "text": "hi"}
    # token for another session
    assert (
        client.post(url, json=body, headers={"Authorization": f"Bearer {two['token']}"}).status_code
        == 401
    )
    # right token, different origin
    wrong_origin = client.post(
        url,
        json=body,
        headers={"Authorization": f"Bearer {one['token']}", "Origin": "http://localhost:8081"},
    )
    assert wrong_origin.status_code == 403
    assert client.post(url, json=body).status_code == 401


def test_tampered_and_expired_tokens_are_rejected(client: TestClient) -> None:
    public_id = make_agent(client)
    approve(client)
    session = start(client, public_id).json()
    url = f"/api/v1/public/widget/session/{session['session_id']}/events"
    body = {"type": "message", "text": "hi"}
    forged = jwt.encode(
        {"sid": session["session_id"], "tid": "x", "origin": SITE, "exp": 9999999999},
        "wrong-key-wrong-key-wrong-key-123456",
        algorithm="HS256",
    )
    expired = jwt.encode(
        {"sid": session["session_id"], "tid": "x", "origin": SITE, "exp": 1},
        get_settings().widget_signing_key,
        algorithm="HS256",
    )
    for token in (forged, expired):
        assert (
            client.post(url, json=body, headers={"Authorization": f"Bearer {token}"}).status_code
            == 401
        )


def test_message_validation_and_rate_limit(client: TestClient) -> None:
    public_id = make_agent(client)
    approve(client)
    session = start(client, public_id).json()
    url = f"/api/v1/public/widget/session/{session['session_id']}/events"
    headers = {"Authorization": f"Bearer {session['token']}", "Origin": SITE}
    assert (
        client.post(url, json={"type": "message", "text": ""}, headers=headers).status_code == 422
    )
    assert (
        client.post(url, json={"type": "message", "text": "x" * 1001}, headers=headers).status_code
        == 422
    )
    statuses = [
        client.post(url, json={"type": "message", "text": "hi"}, headers=headers).status_code
        for _ in range(32)
    ]
    assert statuses.count(200) == 30 and statuses[-1] == 429
    reset_limiters(get_settings())


def test_preflight(client: TestClient) -> None:
    response = client.options(
        "/api/v1/public/widget/session",
        headers={"Origin": SITE, "Access-Control-Request-Method": "POST"},
    )
    assert response.status_code == 204
    assert "authorization" in response.headers["access-control-allow-headers"]


def test_domain_admin_endpoints(client: TestClient) -> None:
    assert (
        client.post(
            "/api/v1/domains", headers=auth("a", "analyst"), json={"hostname": "x.example.com"}
        ).status_code
        == 403
    )
    assert (
        client.post(
            "/api/v1/domains", headers=auth("a"), json={"hostname": "https://x.example.com"}
        ).status_code
        == 422
    )
    first = client.post("/api/v1/domains", headers=auth("a"), json={"hostname": "X.Example.com"})
    assert first.status_code == 201 and first.json()["hostname"] == "x.example.com"
    assert first.json()["status"] == "pending"
    assert (
        client.post(
            "/api/v1/domains", headers=auth("a"), json={"hostname": "x.example.com"}
        ).status_code
        == 409
    )
    assert client.get("/api/v1/domains", headers=auth("b")).json() == []
