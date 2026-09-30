"""Project exceptions.

Error messages must stay free of API keys, OAuth tokens, and other secrets.
"""

from __future__ import annotations


class OutreachError(Exception):
    """Base error for CreatorReach AI."""


class ConfigError(OutreachError):
    """Raised when configuration is missing or invalid."""


class YouTubeAPIError(OutreachError):
    """Base YouTube Data API error."""


class QuotaExceeded(YouTubeAPIError):
    """Local safety budget or remote daily quota exhausted."""


class TransientYouTubeError(YouTubeAPIError):
    """Retryable 429 / 5xx YouTube error."""


class PermanentYouTubeError(YouTubeAPIError):
    """Non-retryable YouTube error (auth, invalid, forbidden, not found, quotaExceeded)."""


class ValidationError(OutreachError):
    """Structured output or message validation failed."""


class ApprovalError(OutreachError):
    """Human-approval gate rejected the action."""


class SendError(OutreachError):
    """Delivery failed after approval checks."""
