"""PII (Personally Identifiable Information) filtering service."""

import re
from typing import NamedTuple

from mag.config import get_settings


class PIIPattern(NamedTuple):
    """A PII detection pattern."""

    name: str
    pattern: re.Pattern
    replacement: str


# Common PII patterns
_PII_PATTERNS: list[PIIPattern] = [
    # Social Security Numbers (US)
    PIIPattern(
        name="ssn",
        pattern=re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),
        replacement="[REDACTED-SSN]",
    ),
    # Credit Card Numbers (13-19 digits, with optional separators)
    PIIPattern(
        name="credit_card",
        pattern=re.compile(r"\b(?:\d{4}[- ]?){3,4}\d{1,4}\b"),
        replacement="[REDACTED-CC]",
    ),
    # Bank Account Numbers (8-17 digits)
    PIIPattern(
        name="bank_account",
        pattern=re.compile(r"\b(?:account|acct)\.?\s*#?\s*\d{8,17}\b", re.IGNORECASE),
        replacement="[REDACTED-ACCOUNT]",
    ),
    # Routing Numbers (9 digits)
    PIIPattern(
        name="routing_number",
        pattern=re.compile(r"\b(?:routing|aba)\.?\s*#?\s*\d{9}\b", re.IGNORECASE),
        replacement="[REDACTED-ROUTING]",
    ),
    # Passwords in context
    PIIPattern(
        name="password",
        pattern=re.compile(
            r"\b(?:password|passwd|pwd|pin|passcode)[:\s]+\S+", re.IGNORECASE
        ),
        replacement="[REDACTED-PASSWORD]",
    ),
    # API Keys / Tokens (common patterns)
    PIIPattern(
        name="api_key",
        pattern=re.compile(
            r"\b(?:api[_-]?key|token|secret|bearer)[:\s]+[A-Za-z0-9_\-]{20,}\b",
            re.IGNORECASE,
        ),
        replacement="[REDACTED-KEY]",
    ),
]


def filter_pii(text: str | None) -> str | None:
    """Filter PII from text based on configured filter mode.

    Args:
        text: The text to filter (can be None)

    Returns:
        Filtered text with PII replaced, or original if filtering disabled
    """
    if text is None:
        return None

    settings = get_settings()

    # Check if PII filtering is enabled
    if not settings.pii_filter:
        return text

    if settings.pii_filter == "regex":
        return _filter_regex(text)
    # Future: elif settings.pii_filter == "presidio": ...

    # Unknown filter mode, return original
    return text


def _filter_regex(text: str) -> str:
    """Apply regex-based PII filtering."""
    result = text
    for pattern in _PII_PATTERNS:
        result = pattern.pattern.sub(pattern.replacement, result)
    return result
