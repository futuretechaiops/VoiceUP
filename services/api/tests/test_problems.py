from conftest import auth
from fastapi.testclient import TestClient


def test_health(client: TestClient) -> None:
    assert client.get("/health/live").json() == {"status": "ok"}
    assert client.get("/health/ready").json() == {"status": "ready"}


def test_validation_errors_use_problem_json(client: TestClient) -> None:
    response = client.post("/api/v1/agents", headers=auth("a"), json={"name": "x"})
    assert response.status_code == 422
    assert response.headers["content-type"].startswith("application/problem+json")
    body = response.json()
    assert body["code"] == "VALIDATION_ERROR"
    assert {e["field"] for e in body["errors"]} >= {"name", "primary_objective"}
    assert body["request_id"] == response.headers["X-Request-Id"]


def test_request_id_is_echoed(client: TestClient) -> None:
    response = client.get("/health/live", headers={"X-Request-Id": "req-123"})
    assert response.headers["X-Request-Id"] == "req-123"


def test_unauthenticated_problem_shape(client: TestClient) -> None:
    response = client.get("/api/v1/me")
    assert response.status_code == 401
    assert response.json()["code"] == "HTTP_401"
