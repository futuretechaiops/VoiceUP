from conftest import A_TENANT, B_TENANT, auth
from fastapi.testclient import TestClient

A_ADMIN_MEMBERSHIP = "ma000000-0000-0000-0000-000000000001"
A_ANALYST_MEMBERSHIP = "ma000000-0000-0000-0000-000000000002"
B_MEMBERSHIP = "mb000000-0000-0000-0000-000000000001"


def test_list_members_is_tenant_scoped(client: TestClient) -> None:
    body = client.get(f"/api/v1/organisations/{A_TENANT}/members", headers=auth("a")).json()
    emails = {m["email"] for m in body["items"]}
    assert emails == {"a@example.test", "a2@example.test", "m@example.test"}


def test_other_organisation_is_404(client: TestClient) -> None:
    assert client.get(f"/api/v1/organisations/{B_TENANT}", headers=auth("a")).status_code == 404
    assert (
        client.get(f"/api/v1/organisations/{B_TENANT}/members", headers=auth("a")).status_code
        == 404
    )


def test_members_require_admin(client: TestClient) -> None:
    url = f"/api/v1/organisations/{A_TENANT}/members"
    assert client.get(url, headers=auth("a", "sales_agent")).status_code == 403


def test_invitation_stores_only_a_hash(client: TestClient, seeded) -> None:  # type: ignore[no-untyped-def]
    from sqlalchemy import text

    response = client.post(
        f"/api/v1/organisations/{A_TENANT}/invitations",
        headers=auth("a"),
        json={"email": "New.Person@Example.com", "role": "sales_agent"},
    )
    assert response.status_code == 201
    token = response.json()["token"]
    with seeded.connect() as conn:
        stored = conn.execute(text("SELECT email, token_hash FROM invitations")).one()
    assert stored.email == "new.person@example.com"
    assert token not in stored.token_hash and len(stored.token_hash) == 64


def test_cannot_invite_platform_admin(client: TestClient) -> None:
    response = client.post(
        f"/api/v1/organisations/{A_TENANT}/invitations",
        headers=auth("a"),
        json={"email": "x@example.com", "role": "platform_admin"},
    )
    assert response.status_code == 422


def test_change_role_and_audit(client: TestClient) -> None:
    url = f"/api/v1/organisations/{A_TENANT}/members/{A_ANALYST_MEMBERSHIP}"
    response = client.patch(url, headers=auth("a"), json={"role": "sales_manager"})
    assert response.status_code == 200
    assert response.json()["role"] == "sales_manager"


def test_cannot_change_role_in_another_tenant(client: TestClient) -> None:
    url = f"/api/v1/organisations/{A_TENANT}/members/{B_MEMBERSHIP}"
    assert client.patch(url, headers=auth("a"), json={"role": "analyst"}).status_code == 404


def test_last_administrator_cannot_be_demoted(client: TestClient) -> None:
    url = f"/api/v1/organisations/{A_TENANT}/members/{A_ADMIN_MEMBERSHIP}"
    response = client.patch(url, headers=auth("a"), json={"role": "analyst"})
    assert response.status_code == 409
