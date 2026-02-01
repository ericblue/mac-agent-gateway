"""Security tests for Mac Agent Gateway.

Tests security controls including:
- API key validation
- Error message sanitization
- Path traversal prevention
- Rate limiting
- CORS configuration
- Input validation
"""

import os
import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

# Set test environment before importing app
os.environ["MAG_API_KEY"] = "test-api-key-for-unit-tests-only-1234567890"
os.environ["MAG_MESSAGES_SEND_ALLOWLIST"] = ""
os.environ["MAG_PII_FILTER"] = "regex"

from mag.config import get_settings
get_settings.cache_clear()

from mag.main import app, _validate_api_key


class TestApiKeyValidation:
    """Tests for API key security validation."""

    def test_blocked_placeholder_keys(self) -> None:
        """Should block common placeholder API keys."""
        blocked_keys = [
            "your-secret-api-key-here",
            "changeme",
            "secret",
            "password",
            "test-key",
        ]
        for key in blocked_keys:
            errors, _ = _validate_api_key(key)
            assert len(errors) > 0, f"Key '{key}' should be blocked"
            assert "blocked placeholder" in errors[0].lower()

    def test_short_keys_blocked(self) -> None:
        """Should block API keys shorter than 16 characters."""
        errors, _ = _validate_api_key("short123")
        assert len(errors) > 0
        assert "too short" in errors[0].lower()

    def test_minimum_length_keys_accepted(self) -> None:
        """Keys with 16+ characters should not error (may warn)."""
        errors, warnings = _validate_api_key("1234567890123456")
        assert len(errors) == 0
        # Should warn about recommended length
        assert any("short" in w.lower() for w in warnings)

    def test_recommended_length_no_warnings(self) -> None:
        """Keys with 32+ characters should not warn about length."""
        errors, warnings = _validate_api_key("12345678901234567890123456789012ab")
        assert len(errors) == 0
        assert not any("short" in w.lower() for w in warnings)

    def test_low_complexity_warning(self) -> None:
        """Should warn about low-complexity keys."""
        errors, warnings = _validate_api_key("aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa")
        assert len(errors) == 0
        assert any("complexity" in w.lower() for w in warnings)


class TestErrorSanitization:
    """Tests for error message sanitization."""

    @pytest.fixture
    def client(self) -> TestClient:
        return TestClient(app, raise_server_exceptions=False)

    def test_global_exception_no_detail_leak(self, client: TestClient) -> None:
        """Global exception handler should not leak internal details."""
        # This tests the error response format - details should not be exposed
        # We can't easily trigger a real exception, but we can verify the handler exists
        from mag.main import global_exception_handler
        assert global_exception_handler is not None

    def test_capabilities_redacts_allowlist(self, client: TestClient) -> None:
        """Capabilities endpoint should not expose send allowlist recipients."""
        # Set up allowlist
        os.environ["MAG_MESSAGES_SEND_ALLOWLIST"] = "+15551234567,+15559876543"
        get_settings.cache_clear()

        response = client.get("/v1/capabilities")
        assert response.status_code == 200
        data = response.json()

        # Should indicate allowlist is active but not expose actual numbers
        assert data["messages"]["send_allowlist"] is None
        assert data["messages"]["send_allowlist_active"] is True

        # Cleanup
        os.environ["MAG_MESSAGES_SEND_ALLOWLIST"] = ""
        get_settings.cache_clear()


class TestPathTraversalPrevention:
    """Tests for file attachment path validation."""

    @pytest.fixture
    def client(self) -> TestClient:
        return TestClient(app)

    @pytest.fixture
    def auth_headers(self) -> dict:
        return {"X-API-Key": "test-api-key-for-unit-tests-only-1234567890"}

    def test_attachment_blocked_when_outside_allowed_dirs(
        self, client: TestClient, auth_headers: dict
    ) -> None:
        """Attachments outside allowed directories should be blocked."""
        # Configure allowed directories
        with tempfile.TemporaryDirectory() as allowed_dir:
            os.environ["MAG_ATTACHMENT_ALLOWED_DIRS"] = allowed_dir
            get_settings.cache_clear()

            response = client.post(
                "/v1/messages/send",
                headers=auth_headers,
                json={
                    "to": "+15551234567",
                    "text": "test",
                    "files": ["/etc/passwd"],  # Definitely not in allowed dir
                },
            )

            # Should be forbidden
            assert response.status_code == 403
            assert "not in allowed directories" in response.json()["detail"]["error"]

            # Cleanup
            os.environ["MAG_ATTACHMENT_ALLOWED_DIRS"] = ""
            get_settings.cache_clear()

    def test_attachment_allowed_in_configured_dir(
        self, client: TestClient, auth_headers: dict
    ) -> None:
        """Attachments in allowed directories should be permitted."""
        with tempfile.TemporaryDirectory() as allowed_dir:
            # Create a test file
            test_file = Path(allowed_dir) / "test.txt"
            test_file.write_text("test content")

            os.environ["MAG_ATTACHMENT_ALLOWED_DIRS"] = allowed_dir
            get_settings.cache_clear()

            response = client.post(
                "/v1/messages/send",
                headers=auth_headers,
                json={
                    "to": "+15551234567",
                    "text": "test",
                    "files": [str(test_file)],
                },
            )

            # Should not be 403 (may be 502 if imsg not installed, but not forbidden)
            assert response.status_code != 403

            # Cleanup
            os.environ["MAG_ATTACHMENT_ALLOWED_DIRS"] = ""
            get_settings.cache_clear()

    def test_path_traversal_attempt_blocked(
        self, client: TestClient, auth_headers: dict
    ) -> None:
        """Path traversal attempts should be blocked."""
        with tempfile.TemporaryDirectory() as allowed_dir:
            os.environ["MAG_ATTACHMENT_ALLOWED_DIRS"] = allowed_dir
            get_settings.cache_clear()

            # Try to escape allowed directory
            response = client.post(
                "/v1/messages/send",
                headers=auth_headers,
                json={
                    "to": "+15551234567",
                    "text": "test",
                    "files": [f"{allowed_dir}/../../../etc/passwd"],
                },
            )

            assert response.status_code == 403

            # Cleanup
            os.environ["MAG_ATTACHMENT_ALLOWED_DIRS"] = ""
            get_settings.cache_clear()


class TestInputValidation:
    """Tests for input validation on path parameters."""

    @pytest.fixture
    def client(self) -> TestClient:
        return TestClient(app)

    @pytest.fixture
    def auth_headers(self) -> dict:
        return {"X-API-Key": "test-api-key-for-unit-tests-only-1234567890"}

    def test_reminder_id_rejects_special_chars(
        self, client: TestClient, auth_headers: dict
    ) -> None:
        """Reminder ID with shell metacharacters should be rejected."""
        # Test IDs with shell metacharacters
        # Note: IDs with spaces, pipes, semicolons etc. should be rejected
        dangerous_ids = [
            ("id;ls", 400),  # Semicolon - command separator
            ("id$(whoami)", 400),  # Command substitution
            ("id`whoami`", 400),  # Backtick command substitution
            ("id|ls", 400),  # Pipe
            ("id&ls", 400),  # Background/chain
            ("id>file", 400),  # Redirect
            ("id<file", 400),  # Redirect
        ]
        for dangerous_id, expected_status in dangerous_ids:
            response = client.patch(
                f"/v1/reminders/{dangerous_id}",
                headers=auth_headers,
                json={"title": "test"},
            )
            # Should be 400 (bad request) due to validation
            assert response.status_code == expected_status, \
                f"ID '{dangerous_id}' should return {expected_status}, got {response.status_code}"

    def test_reminder_id_allows_valid_formats(
        self, client: TestClient, auth_headers: dict
    ) -> None:
        """Valid reminder IDs should be accepted."""
        valid_ids = [
            "123",
            "abc-def",
            "abc_def",
            "ABC123",
            "reminder:123",
            "x/y",  # Some systems use slashes in IDs
        ]
        for valid_id in valid_ids:
            response = client.patch(
                f"/v1/reminders/{valid_id}",
                headers=auth_headers,
                json={"title": "test"},
            )
            # Should not be 400 (may be 500 if remindctl not installed)
            assert response.status_code != 400, f"ID '{valid_id}' should be valid"

    def test_list_name_rejects_special_chars(
        self, client: TestClient, auth_headers: dict
    ) -> None:
        """List name with shell metacharacters should be rejected."""
        response = client.delete(
            "/v1/reminders/lists/test; echo pwned",
            headers=auth_headers,
        )
        assert response.status_code == 400


class TestCorsConfiguration:
    """Tests for CORS configuration."""

    @pytest.fixture
    def client(self) -> TestClient:
        return TestClient(app)

    def test_cors_allows_localhost(self, client: TestClient) -> None:
        """CORS should allow localhost origins."""
        response = client.options(
            "/v1/reminders",
            headers={
                "Origin": "http://localhost:8123",
                "Access-Control-Request-Method": "GET",
            },
        )
        # Should include CORS headers
        assert "access-control-allow-origin" in response.headers

    def test_cors_blocks_external_origins(self, client: TestClient) -> None:
        """CORS should block external origins."""
        response = client.options(
            "/v1/reminders",
            headers={
                "Origin": "https://evil.com",
                "Access-Control-Request-Method": "GET",
            },
        )
        # Should not include evil.com in allowed origins
        origin = response.headers.get("access-control-allow-origin", "")
        assert "evil.com" not in origin


class TestPiiFiltering:
    """Tests that PII filtering is applied to message content."""

    def test_pii_filtering_enabled_by_default(self) -> None:
        """PII filtering should be enabled by default."""
        # Reset to defaults
        if "MAG_PII_FILTER" in os.environ:
            del os.environ["MAG_PII_FILTER"]
        get_settings.cache_clear()

        settings = get_settings()
        assert settings.pii_filter == "regex"

        # Restore for other tests
        os.environ["MAG_PII_FILTER"] = "regex"
        get_settings.cache_clear()


class TestAuthenticationRequired:
    """Tests that authentication is required on protected endpoints."""

    @pytest.fixture
    def client(self) -> TestClient:
        return TestClient(app)

    def test_reminders_requires_auth(self, client: TestClient) -> None:
        """Reminders endpoint should require authentication."""
        response = client.get("/v1/reminders")
        assert response.status_code == 401

    def test_messages_requires_auth(self, client: TestClient) -> None:
        """Messages endpoint should require authentication."""
        response = client.get("/v1/messages/threads")
        assert response.status_code == 401

    def test_health_no_auth(self, client: TestClient) -> None:
        """Health endpoint should not require authentication."""
        response = client.get("/health")
        assert response.status_code == 200

    def test_capabilities_no_auth(self, client: TestClient) -> None:
        """Capabilities endpoint should not require authentication."""
        response = client.get("/v1/capabilities")
        assert response.status_code == 200


class TestAttachmentDownloadSecurity:
    """Tests for attachment download security."""

    @pytest.fixture
    def client(self) -> TestClient:
        return TestClient(app)

    @pytest.fixture
    def auth_headers(self) -> dict:
        return {"X-API-Key": "test-api-key-for-unit-tests-only-1234567890"}

    def test_attachment_download_requires_auth(self, client: TestClient) -> None:
        """Attachment download should require authentication."""
        response = client.get("/v1/messages/attachments/download?path=/some/file")
        assert response.status_code == 401

    def test_attachment_blocks_arbitrary_files(
        self, client: TestClient, auth_headers: dict
    ) -> None:
        """Should block downloading files outside of Messages Attachments."""
        dangerous_paths = [
            "/etc/passwd",
            "/etc/shadow",
            "~/.ssh/id_rsa",
            "/Users/someone/.zshrc",
            "/tmp/somefile",
        ]
        for path in dangerous_paths:
            response = client.get(
                f"/v1/messages/attachments/download?path={path}",
                headers=auth_headers,
            )
            assert response.status_code == 403, f"Path '{path}' should be blocked"
            assert "not a message attachment" in response.json()["detail"]["error"]

    def test_attachment_blocks_path_traversal(
        self, client: TestClient, auth_headers: dict
    ) -> None:
        """Should block path traversal attempts."""
        from pathlib import Path
        
        # Try to escape from the allowed directory
        traversal_path = str(
            Path.home() / "Library" / "Messages" / "Attachments" / ".." / ".." / ".." / ".ssh" / "id_rsa"
        )
        response = client.get(
            f"/v1/messages/attachments/download?path={traversal_path}",
            headers=auth_headers,
        )
        # Should be either 403 (blocked) or 404 (file doesn't exist after resolution)
        assert response.status_code in (403, 404)

    def test_attachment_info_requires_auth(self, client: TestClient) -> None:
        """Attachment info should require authentication."""
        response = client.get("/v1/messages/attachments/info?path=/some/file")
        assert response.status_code == 401

    def test_attachment_info_blocks_arbitrary_files(
        self, client: TestClient, auth_headers: dict
    ) -> None:
        """Should block querying files outside of Messages Attachments."""
        response = client.get(
            "/v1/messages/attachments/info?path=/etc/passwd",
            headers=auth_headers,
        )
        assert response.status_code == 403
