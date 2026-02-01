"""Tests for PII filtering service."""

import os
import pytest

# Ensure clean test environment
os.environ.setdefault("MAG_API_KEY", "test-api-key-for-unit-tests-only-1234567890")
os.environ["MAG_PII_FILTER"] = ""

from mag.config import get_settings
from mag.services.pii import filter_pii, _filter_regex


class TestPIIFilterDisabled:
    """Tests when PII filtering is disabled."""

    def setup_method(self) -> None:
        """Clear settings cache before each test."""
        os.environ["MAG_PII_FILTER"] = ""
        get_settings.cache_clear()

    def test_filter_returns_original_when_disabled(self) -> None:
        """Filter should return original text when disabled."""
        text = "My SSN is 123-45-6789"
        assert filter_pii(text) == text

    def test_filter_handles_none(self) -> None:
        """Filter should handle None input."""
        assert filter_pii(None) is None


class TestPIIFilterRegex:
    """Tests for regex-based PII filtering."""

    def setup_method(self) -> None:
        """Enable regex filter before each test."""
        os.environ["MAG_PII_FILTER"] = "regex"
        get_settings.cache_clear()

    def teardown_method(self) -> None:
        """Reset filter after each test."""
        os.environ["MAG_PII_FILTER"] = ""
        get_settings.cache_clear()

    def test_filter_ssn(self) -> None:
        """Should mask Social Security Numbers."""
        text = "My SSN is 123-45-6789 and yours is 987-65-4321"
        result = filter_pii(text)
        assert "123-45-6789" not in result
        assert "987-65-4321" not in result
        assert "[REDACTED-SSN]" in result

    def test_filter_credit_card(self) -> None:
        """Should mask credit card numbers."""
        text = "Card: 4111-1111-1111-1111"
        result = filter_pii(text)
        assert "4111" not in result
        assert "[REDACTED-CC]" in result

    def test_filter_credit_card_no_separators(self) -> None:
        """Should mask credit card numbers without separators."""
        text = "Card: 4111111111111111"
        result = filter_pii(text)
        assert "4111111111111111" not in result
        assert "[REDACTED-CC]" in result

    def test_filter_bank_account(self) -> None:
        """Should mask bank account numbers."""
        # Note: Very long account numbers may also match credit card pattern
        text = "Account #12345678"  # 8 digits - won't match CC pattern
        result = filter_pii(text)
        assert "12345678" not in result
        assert "[REDACTED-ACCOUNT]" in result

    def test_filter_bank_account_variations(self) -> None:
        """Should mask various bank account formats."""
        texts = [
            "account 12345678901234",
            "acct #12345678901234",
            "ACCT: 12345678901234",
        ]
        for text in texts:
            result = filter_pii(text)
            assert "12345678901234" not in result

    def test_filter_routing_number(self) -> None:
        """Should mask routing numbers."""
        text = "Routing #123456789"
        result = filter_pii(text)
        assert "123456789" not in result
        assert "[REDACTED-ROUTING]" in result

    def test_filter_password(self) -> None:
        """Should mask passwords in context."""
        texts = [
            "password: secret123",
            "Password is myp@ssw0rd",
            "pwd: abc123xyz",
            "PIN: 1234",
        ]
        for text in texts:
            result = filter_pii(text)
            assert "[REDACTED-PASSWORD]" in result

    def test_filter_api_key(self) -> None:
        """Should mask API keys and tokens."""
        texts = [
            "api_key: sk-abc123xyz789def456ghi012",
            "token: eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9",
            "secret: veryLongSecretKeyThatShouldBeRedacted",
        ]
        for text in texts:
            result = filter_pii(text)
            assert "[REDACTED-KEY]" in result

    def test_filter_preserves_normal_text(self) -> None:
        """Should not alter normal text without PII."""
        text = "Hello, can we meet at 3pm tomorrow? The weather is nice."
        result = filter_pii(text)
        assert result == text

    def test_filter_multiple_patterns(self) -> None:
        """Should mask multiple PII patterns in one message."""
        text = "SSN: 123-45-6789, Card: 4111-1111-1111-1111, password: secret"
        result = filter_pii(text)
        assert "[REDACTED-SSN]" in result
        assert "[REDACTED-CC]" in result
        assert "[REDACTED-PASSWORD]" in result

    def test_filter_handles_none(self) -> None:
        """Filter should handle None input even when enabled."""
        assert filter_pii(None) is None

    def test_filter_handles_empty_string(self) -> None:
        """Filter should handle empty string."""
        assert filter_pii("") == ""


class TestDirectRegexFilter:
    """Tests for the _filter_regex function directly."""

    def test_ssn_exact_format(self) -> None:
        """Test exact SSN format matching."""
        assert _filter_regex("123-45-6789") == "[REDACTED-SSN]"

    def test_ssn_not_similar_patterns(self) -> None:
        """Test that similar but non-SSN patterns are not matched."""
        # Phone numbers should not be matched as SSN
        assert _filter_regex("123-456-7890") == "123-456-7890"

    def test_preserves_urls(self) -> None:
        """Test that URLs are preserved."""
        url = "https://example.com/page?id=12345"
        assert _filter_regex(url) == url

    def test_preserves_dates(self) -> None:
        """Test that dates are preserved."""
        date = "2024-01-15"
        assert _filter_regex(date) == date
