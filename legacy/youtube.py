"""YouTube Data API v3 client: batching, caching, retries and quota accounting."""
from __future__ import annotations

import json
import logging
import time
from typing import Any, Dict, List, Optional

import requests

log = logging.getLogger(__name__)

BASE_URL = "https://www.googleapis.com/youtube/v3"
# Quota units per call (see developers.google.com/youtube/v3/determine_quota_cost).
COSTS = {"search": 100, "channels": 1, "playlistItems": 1, "videos": 1}


class YouTubeAPIError(Exception):
    pass


class QuotaExceeded(YouTubeAPIError):
    pass


def _int(value: Any) -> Optional[int]:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def parse_channel(item: Dict[str, Any]) -> Dict[str, Any]:
    """Normalise a channels.list resource into our influencer fields."""
    snippet = item.get("snippet", {})
    stats = item.get("statistics", {})
    hidden = bool(stats.get("hiddenSubscriberCount"))
    channel_id = item["id"]
    handle = snippet.get("customUrl")
    profile_url = f"https://www.youtube.com/{handle}" if handle and handle.startswith("@") \
        else f"https://www.youtube.com/channel/{channel_id}"
    keywords = item.get("brandingSettings", {}).get("channel", {}).get("keywords", "")
    return {
        "channel_id": channel_id,
        "name": snippet.get("title") or channel_id,
        "handle": handle,
        "profile_url": profile_url,
        "description": snippet.get("description", ""),
        "country": snippet.get("country"),
        "followers": None if hidden else _int(stats.get("subscriberCount")),
        "followers_hidden": int(hidden),
        "total_views": _int(stats.get("viewCount")),
        "video_count": _int(stats.get("videoCount")),
        "uploads_playlist": item.get("contentDetails", {}).get("relatedPlaylists", {}).get("uploads"),
        "channel_keywords": keywords,
    }


def parse_video(item: Dict[str, Any]) -> Dict[str, Any]:
    snippet = item.get("snippet", {})
    stats = item.get("statistics", {})
    return {
        "id": item["id"],
        "title": snippet.get("title", ""),
        "description": snippet.get("description", ""),
        "published_at": snippet.get("publishedAt"),
        "url": f"https://www.youtube.com/watch?v={item['id']}",
        "views": _int(stats.get("viewCount")),
        "likes": _int(stats.get("likeCount")),        # None when the creator hides likes
        "comments": _int(stats.get("commentCount")),  # None when comments are disabled
    }


class YouTubeClient:
    def __init__(self, api_key: str, cache=None, session: Optional[requests.Session] = None,
                 quota_budget: int = 9000, max_retries: int = 3, backoff: float = 1.0,
                 sleep=time.sleep):
        if not api_key:
            raise YouTubeAPIError("YOUTUBE_API_KEY is not set")
        self.api_key = api_key
        self.cache = cache
        self.session = session or requests.Session()
        self.quota_budget = quota_budget
        self.max_retries = max_retries
        self.backoff = backoff
        self._sleep = sleep
        self.quota_used = 0
        self.cache_hits = 0

    # ---- low level -------------------------------------------------------
    def _request(self, endpoint: str, params: Dict[str, Any]) -> Dict[str, Any]:
        cost = COSTS[endpoint]
        cache_key = f"{endpoint}:{json.dumps(params, sort_keys=True)}"
        if self.cache:
            hit = self.cache.get(cache_key)
            if hit is not None:
                self.cache_hits += 1
                return hit
        if self.quota_used + cost > self.quota_budget:
            raise QuotaExceeded(f"Local quota budget of {self.quota_budget} units reached")

        last_error = "unknown error"
        for attempt in range(self.max_retries + 1):
            try:
                resp = self.session.get(f"{BASE_URL}/{endpoint}", params={**params, "key": self.api_key}, timeout=20)
            except requests.RequestException as exc:
                last_error = str(exc)
            else:
                if resp.status_code == 200:
                    data = resp.json()
                    self.quota_used += cost
                    if self.cache:
                        self.cache.set(cache_key, data)
                    return data
                if resp.status_code == 403 and "quotaExceeded" in resp.text:
                    raise QuotaExceeded("YouTube API daily quota exhausted")
                if resp.status_code not in (429, 500, 502, 503, 504):
                    raise YouTubeAPIError(f"{endpoint} failed with HTTP {resp.status_code}: {resp.text[:200]}")
                last_error = f"HTTP {resp.status_code}"
            if attempt < self.max_retries:
                delay = self.backoff * (2 ** attempt)
                log.warning("%s attempt %d failed (%s); retrying in %.1fs", endpoint, attempt + 1, last_error, delay)
                self._sleep(delay)
        raise YouTubeAPIError(f"{endpoint} failed after retries: {last_error}")

    # ---- high level ------------------------------------------------------
    def search_channels(self, query: str, max_results: int = 50, pages: int = 1) -> List[str]:
        ids: List[str] = []
        token = None
        for _ in range(max(1, pages)):
            params: Dict[str, Any] = {"part": "snippet", "q": query, "type": "channel",
                                      "maxResults": min(max_results, 50)}
            if token:
                params["pageToken"] = token
            data = self._request("search", params)
            for item in data.get("items", []):
                cid = item.get("id", {}).get("channelId") or item.get("snippet", {}).get("channelId")
                if cid:
                    ids.append(cid)
            token = data.get("nextPageToken")
            if not token:
                break
        return ids

    def get_channels(self, channel_ids: List[str]) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        unique = list(dict.fromkeys(channel_ids))
        for start in range(0, len(unique), 50):
            batch = unique[start:start + 50]
            data = self._request("channels", {
                "part": "snippet,statistics,contentDetails,brandingSettings",
                "id": ",".join(batch), "maxResults": 50})
            out.extend(parse_channel(i) for i in data.get("items", []))
        return out

    def get_recent_videos(self, uploads_playlist: str, n: int = 10) -> List[Dict[str, Any]]:
        """Latest n uploads with stats. Costs 2 units (playlistItems + videos) instead of a 100-unit search."""
        data = self._request("playlistItems", {"part": "contentDetails", "playlistId": uploads_playlist,
                                               "maxResults": min(n, 50)})
        video_ids = [i["contentDetails"]["videoId"] for i in data.get("items", [])
                     if i.get("contentDetails", {}).get("videoId")]
        if not video_ids:
            return []
        vdata = self._request("videos", {"part": "snippet,statistics", "id": ",".join(video_ids)})
        videos = [parse_video(i) for i in vdata.get("items", [])]
        videos.sort(key=lambda v: v.get("published_at") or "", reverse=True)
        return videos[:n]
