from conftest import auth
from fastapi.testclient import TestClient

BODY = {"name": "Ava", "primary_objective": "Generate qualified enquiries"}


def test_agent_isolation(client: TestClient) -> None:
    created = client.post("/api/v1/agents", headers=auth("a"), json=BODY)
    assert created.status_code == 201
    agent_id = created.json()["id"]

    assert client.get(f"/api/v1/agents/{agent_id}", headers=auth("a")).status_code == 200
    assert client.get(f"/api/v1/agents/{agent_id}", headers=auth("b")).status_code == 404

    foreign = client.get("/api/v1/agents", headers=auth("b"))
    assert foreign.status_code == 200
    assert foreign.json() == {"items": [], "next_cursor": None}


def test_create_agent_survives_commit_regression(client: TestClient) -> None:
    """v0.1.0 returned 500: tenant context was lost after commit, so refresh found no row."""
    response = client.post("/api/v1/agents", headers=auth("a"), json=BODY)
    assert response.status_code == 201
    assert response.json()["name"] == "Ava"


def test_creating_an_agent_writes_an_audit_event(client: TestClient, seeded) -> None:  # type: ignore[no-untyped-def]
    client.post("/api/v1/agents", headers=auth("a"), json=BODY)
    from sqlalchemy import text

    with seeded.connect() as conn:
        actions = conn.execute(text("SELECT action FROM audit_events")).scalars().all()
    assert actions == ["agent.created"]


def test_cursor_pagination(client: TestClient) -> None:
    for i in range(3):
        client.post("/api/v1/agents", headers=auth("a"), json={**BODY, "name": f"Agent {i}"})
    first = client.get("/api/v1/agents?limit=2", headers=auth("a")).json()
    assert len(first["items"]) == 2 and first["next_cursor"]
    second = client.get(
        f"/api/v1/agents?limit=2&cursor={first['next_cursor']}", headers=auth("a")
    ).json()
    assert len(second["items"]) == 1 and second["next_cursor"] is None


def test_analyst_cannot_create_agent(client: TestClient) -> None:
    response = client.post("/api/v1/agents", headers=auth("a", "analyst"), json=BODY)
    assert response.status_code == 403


def test_authentication_is_required(client: TestClient) -> None:
    assert client.get("/api/v1/agents").status_code == 401
