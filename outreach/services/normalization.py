"""Normalize YouTube API channel/video resources into SQLite models."""

from __future__ import annotations

from typing import Any, Dict, Optional

from outreach.time_utils import utc_now_iso

FOLLOWERS_SOURCE = "api_reported"


def _int(value: Any) -> Optional[int]:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def normalize_channel(item: Dict[str, Any], *, source_query: Optional[str] = None,
                      discovery_run_id: Optional[int] = None) -> Dict[str, Any]:
    """Convert a channels.list resource into influencer fields. Never fabricates emails."""
    snippet = item.get("snippet") or {}
    stats = item.get("statistics") or {}
    hidden = bool(stats.get("hiddenSubscriberCount"))
    channel_id = item.get("id")
    if not channel_id:
        raise ValueError("channel resource missing id")
    handle = snippet.get("customUrl")
    if handle and str(handle).startswith("@"):
        profile_url = f"https://www.youtube.com/{handle}"
    else:
        profile_url = f"https://www.youtube.com/channel/{channel_id}"
    keywords = (item.get("brandingSettings") or {}).get("channel", {}).get("keywords", "")
    uploads = (item.get("contentDetails") or {}).get("relatedPlaylists", {}).get("uploads")
    followers = None if hidden else _int(stats.get("subscriberCount"))
    return {
        "id": f"yt_{channel_id}",
        "platform": "YouTube",
        "external_id": channel_id,
        "name": snippet.get("title") or channel_id,
        "handle": handle,
        "profile_url": profile_url,
        "description": snippet.get("description") or "",
        "followers": followers,
        "followers_source": FOLLOWERS_SOURCE if followers is not None else "Not Found",
        "followers_hidden": int(hidden),
        "uploads_playlist_id": uploads,
        "total_views": _int(stats.get("viewCount")),
        "video_count": _int(stats.get("videoCount")),
        "channel_keywords": keywords or "",
        "creator_country": snippet.get("country"),
        "audience_age": "Not Found",
        "audience_gender": "Not Found",
        "audience_geography": "Not Found",
        "contact_email": "Not Found",
        "email_status": "Not Found",
        "email_source_url": "Not Found",
        "website": "Not Found",
        "instagram_url": "Not Found",
        "tiktok_url": "Not Found",
        "source_query": source_query,
        "discovery_run_id": discovery_run_id,
        "last_refreshed_at": utc_now_iso(),
        "qualification_status": "DISCOVERED",
    }


def normalize_video(item: Dict[str, Any], influencer_id: str) -> Dict[str, Any]:
    snippet = item.get("snippet") or {}
    stats = item.get("statistics") or {}
    video_id = item.get("id")
    if not video_id:
        raise ValueError("video resource missing id")
    return {
        "id": video_id,
        "influencer_id": influencer_id,
        "external_id": video_id,
        "title": snippet.get("title") or "",
        "description": snippet.get("description") or "",
        "published_at": snippet.get("publishedAt"),
        "url": f"https://www.youtube.com/watch?v={video_id}",
        "views": _int(stats.get("viewCount")),
        "likes": _int(stats.get("likeCount")),  # None when likes are hidden
        "comments": _int(stats.get("commentCount")),
        "retrieved_at": utc_now_iso(),
    }
