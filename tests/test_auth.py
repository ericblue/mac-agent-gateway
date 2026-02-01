"""Tests for API key authentication."""

from fastapi.testclient import TestClient


def test_health_no_auth_required(client: TestClient) -> None:
    """Health endpoint should not require authentication."""
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_openapi_no_auth_required(client: TestClient) -> None:
    """OpenAPI endpoint should not require authentication."""
    response = client.get("/openapi.json")
    assert response.status_code == 200
    assert "openapi" in response.json()


def test_protected_endpoint_missing_api_key(client: TestClient) -> None:
    """Protected endpoints should return 401 without API key."""
    response = client.get("/v1/reminders")
    assert response.status_code == 401
    assert "Missing API key" in response.json()["detail"]


def test_protected_endpoint_invalid_api_key(client: TestClient) -> None:
    """Protected endpoints should return 401 with invalid API key."""
    response = client.get("/v1/reminders", headers={"X-API-Key": "wrong-key"})
    assert response.status_code == 401
    assert "Invalid API key" in response.json()["detail"]


def test_protected_endpoint_valid_api_key(client: TestClient, auth_headers: dict) -> None:
    """Protected endpoints should work with valid API key."""
    response = client.get("/v1/reminders", headers=auth_headers)
    # May return 404 or 405 since no endpoints defined yet, but not 401
    assert response.status_code != 401
