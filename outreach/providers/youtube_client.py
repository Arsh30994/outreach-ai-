"""YouTube Data API v3 client with cache, quota reservation, and typed errors."""

from __future__ import annotations

import json
import logging
import random
import time
from typing import Any, Callable, Dict, List, Optional, Protocol

from outreach.exceptions import (
    PermanentYouTubeError,
    QuotaExceeded,
    TransientYouTubeError,
    YouTubeAPIError,
)
from outreach.logging_config import redact
from outreach.services.cache import ResponseCache
from outreach.services.quota import QuotaManager

log = logging.getLogger(__name__)

RequestFn = Callable[[str, Dict[str, Any]], Dict[str, Any]]


class Transport(Protocol):
    def request(self, endpoint: str, params: Dict[str, Any]) -> Dict[str, Any]: ...


class GoogleApiTransport:
    """Transport backed by google-api-python-client."""

    def __init__(self, api_key: str):
        try:
            from googleapiclient.discovery import build
        except ImportError as exc:  # pragma: no cover
            raise YouTubeAPIError("google-api-python-client is not installed") from exc
        self._service = build("youtube", "v3", developerKey=api_key, cache_discovery=False)

    def request(self, endpoint: str, params: Dict[str, Any]) -> Dict[str, Any]:
        from googleapiclient.errors import HttpError

        resource = getattr(self._service, endpoint)()
        try:
            return resource.list(**params).execute()
        except HttpError as exc:
            status = int(getattr(exc, "resp", {}).get("status", 0) or 0)
            body = ""
            try:
                body = exc.content.decode("utf-8") if isinstance(exc.content, bytes) else str(exc.content)
            except Exception:
                body = str(exc)
            raise _classify_http_error(status, body) from exc


def _classify_http_error(status: int, body: str) -> YouTubeAPIError:
    text = body or ""
    lower = text.lower()
    if status == 403 and "quotaexceeded" in lower.replace("_", "").replace(" ", ""):
        # google uses quotaExceeded
        pass
    if "quotaExceeded" in text or "quotaexceeded" in lower:
        return QuotaExceeded("YouTube API daily quota exhausted")
    if status in (429, 500, 502, 503, 504):
        return TransientYouTubeError(f"Transient HTTP {status}")
    if status in (400, 401, 403, 404):
        return PermanentYouTubeError(f"Permanent HTTP {status}: {redact(text)[:200]}")
    if status == 0:
        return TransientYouTubeError("Network or transport failure")
    return PermanentYouTubeError(f"HTTP {status}: {redact(text)[:200]}")


class YouTubeClient:
    """Central request wrapper: cache → reserve → call → store."""

    def __init__(
        self,
        api_key: str,
        cache: ResponseCache,
        quota: QuotaManager,
        transport: Optional[Transport] = None,
        request_fn: Optional[RequestFn] = None,
        max_retries: int = 3,
        backoff: float = 0.5,
        sleep: Callable[[float], None] = time.sleep,
        pace_seconds: float = 0.0,
    ):
        if not api_key and transport is None and request_fn is None:
            raise YouTubeAPIError("YOUTUBE_API_KEY is not set")
        self.cache = cache
        self.quota = quota
        self.max_retries = max_retries
        self.backoff = backoff
        self._sleep = sleep
        self.pace_seconds = pace_seconds
        if request_fn is not None:
            self._request_fn = request_fn
        elif transport is not None:
            self._request_fn = transport.request
        else:
            self._request_fn = GoogleApiTransport(api_key).request

    def _cache_key(self, endpoint: str, params: Dict[str, Any]) -> str:
        # Exclude secrets; key is never logged with an API key.
        return f"{endpoint}:{json.dumps(params, sort_keys=True)}"

    def execute(self, endpoint: str, params: Dict[str, Any]) -> Dict[str, Any]:
        cache_key = self._cache_key(endpoint, params)
        cached = self.cache.get(cache_key)
        if cached is not None:
            self.quota.record_cache_hit(endpoint)
            return cached

        self.quota.reserve(endpoint)
        last_error: Exception | None = None
        for attempt in range(self.max_retries + 1):
            try:
                if self.pace_seconds:
                    self._sleep(self.pace_seconds)
                data = self._request_fn(endpoint, params)
                self.cache.set(cache_key, endpoint, data)
                return data
            except QuotaExceeded:
                raise
            except PermanentYouTubeError:
                raise
            except TransientYouTubeError as exc:
                last_error = exc
            except YouTubeAPIError:
                raise
            except Exception as exc:
                # Unknown transport failures are treated as transient once.
                last_error = TransientYouTubeError(str(exc))
            if attempt < self.max_retries:
                delay = self.backoff * (2 ** attempt) + random.uniform(0, 0.1)
                log.warning(
                    "%s attempt %d failed (%s); retrying in %.2fs",
                    endpoint,
                    attempt + 1,
                    redact(str(last_error)),
                    delay,
                )
                self._sleep(delay)
        raise YouTubeAPIError(f"{endpoint} failed after retries: {redact(str(last_error))}")

    def search_channels(self, query: str, max_results: int = 50, pages: int = 1) -> List[Dict[str, Any]]:
        """Return list of {channel_id, query, page} for each search hit. Quota per page."""
        results: List[Dict[str, Any]] = []
        token: Optional[str] = None
        for page_index in range(max(1, pages)):
            params: Dict[str, Any] = {
                "part": "snippet",
                "q": query,
                "type": "channel",
                "maxResults": min(max_results, 50),
            }
            if token:
                params["pageToken"] = token
            data = self.execute("search", params)
            for item in data.get("items", []):
                cid = item.get("id", {}).get("channelId") or item.get("snippet", {}).get("channelId")
                if cid:
                    results.append({"channel_id": cid, "query": query, "page": page_index})
            token = data.get("nextPageToken")
            if not token:
                break
        return results

    def get_channels(self, channel_ids: List[str]) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        unique = list(dict.fromkeys(channel_ids))
        for start in range(0, len(unique), 50):
            batch = unique[start : start + 50]
            data = self.execute(
                "channels",
                {
                    "part": "snippet,statistics,contentDetails,brandingSettings",
                    "id": ",".join(batch),
                    "maxResults": 50,
                },
            )
            out.extend(data.get("items", []))
        return out

    def get_playlist_items(self, uploads_playlist_id: str, max_results: int = 10) -> List[str]:
        data = self.execute(
            "playlistItems",
            {
                "part": "contentDetails",
                "playlistId": uploads_playlist_id,
                "maxResults": min(max_results, 50),
            },
        )
        return [
            i["contentDetails"]["videoId"]
            for i in data.get("items", [])
            if i.get("contentDetails", {}).get("videoId")
        ]

    def get_videos(self, video_ids: List[str]) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        unique = list(dict.fromkeys(video_ids))
        for start in range(0, len(unique), 50):
            batch = unique[start : start + 50]
            data = self.execute(
                "videos",
                {"part": "snippet,statistics", "id": ",".join(batch), "maxResults": 50},
            )
            out.extend(data.get("items", []))
        return out
