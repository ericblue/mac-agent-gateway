"""Pytest fixtures for Mac Agent Gateway tests."""

import os

import pytest
from fastapi.testclient import TestClient

# Set test environment before importing app
os.environ["MAG_API_KEY"] = "test-api-key-for-unit-tests-only-1234567890"
os.environ["MAG_MESSAGES_SEND_ALLOWLIST"] = ""  # Clear allowlist for tests

# Clear settings cache to pick up test environment
from mag.config import get_settings
get_settings.cache_clear()

from mag.main import app


@pytest.fixture
def client() -> TestClient:
    """Create a test client for the FastAPI app."""
    return TestClient(app)


@pytest.fixture
def api_key() -> str:
    """Return the test API key."""
    return "test-api-key-for-unit-tests-only-1234567890"


@pytest.fixture
def auth_headers(api_key: str) -> dict[str, str]:
    """Return headers with the test API key."""
    return {"X-API-Key": api_key}
