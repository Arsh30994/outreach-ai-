"""Approximate public engagement from recent video statistics."""

from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Dict, List, Optional

from outreach.time_utils import utc_now_iso

METHOD = (
    "independently_calculated_public_engagement: "
    "(avg likes + avg comments) / avg views * 100 over latest usable public videos"
)


def calculate_engagement(videos: List[Dict[str, Any]], max_videos: int = 10) -> Dict[str, Any]:
    """Public-data approximation. Not YouTube Analytics."""
    sample = list(videos[:max_videos])
    usable = [
        v for v in sample
        if (v.get("views") or 0) > 0 and v.get("likes") is not None
    ]
    if not usable:
        return {
            "rate": None,
            "method": "Not Found",
            "sample_size": 0,
            "calculated_at": None,
        }
    n = len(usable)
    avg_views = sum(Decimal(v["views"]) for v in usable) / Decimal(n)
    avg_likes = sum(Decimal(v["likes"]) for v in usable) / Decimal(n)
    avg_comments = sum(Decimal(v.get("comments") or 0) for v in usable) / Decimal(n)
    rate = ((avg_likes + avg_comments) / avg_views) * Decimal(100)
    rounded = float(rate.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
    return {
        "rate": rounded,
        "method": METHOD,
        "sample_size": n,
        "calculated_at": utc_now_iso(),
    }


def parse_iso(value: Optional[str]):
    if not value:
        return None
    from datetime import datetime, timezone
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def days_since(value: Optional[str], now=None) -> Optional[int]:
    from datetime import datetime, timezone
    dt = parse_iso(value)
    if dt is None:
        return None
    now = now or datetime.now(timezone.utc)
    return (now - dt).days
