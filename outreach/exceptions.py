"""Project exceptions.

Error messages must stay free of API keys, OAuth tokens, and other secrets.
"""

from __future__ import annotations


class OutreachError(Exception):
    """Base error for CreatorReach AI."""


class ConfigError(OutreachError):
    """Raised when configuration is missing or invalid."""
