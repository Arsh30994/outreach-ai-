"""UTC timestamp helpers. All stored timestamps use timezone-aware UTC."""

from __future__ import annotations

from datetime import datetime, timezone


def utc_now() -> datetime:
    """Return the current time in UTC."""
    return datetime.now(timezone.utc)


def utc_now_iso() -> str:
    """Return the current UTC time as an ISO-8601 string without microseconds."""
    return utc_now().replace(microsecond=0).isoformat()
