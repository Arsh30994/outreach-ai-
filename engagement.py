"""Engagement-rate calculation from public video statistics."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


def calculate_engagement(videos: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Approximate engagement = (avg likes + avg comments) / avg views * 100.

    Videos without a usable view count or with hidden likes are excluded, and the
    sample size is reported so the figure is never presented as more than it is.
    This is a public-data approximation, not creator-side analytics.
    """
    usable = [v for v in videos if (v.get("views") or 0) > 0 and v.get("likes") is not None]
    if not usable:
        return {"rate": None, "method": "Not Found", "sample_size": 0}
    n = len(usable)
    avg_views = sum(v["views"] for v in usable) / n
    avg_likes = sum(v["likes"] for v in usable) / n
    avg_comments = sum((v.get("comments") or 0) for v in usable) / n
    rate = (avg_likes + avg_comments) / avg_views * 100
    return {"rate": round(rate, 2),
            "method": f"calculated_public_data: (avg likes+comments)/avg views over latest {n} videos",
            "sample_size": n}


def parse_iso(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def days_since(value: Optional[str], now: Optional[datetime] = None) -> Optional[int]:
    dt = parse_iso(value)
    if dt is None:
        return None
    now = now or datetime.now(timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return (now - dt).days
