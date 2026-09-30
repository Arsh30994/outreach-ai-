"""Test helpers. All data here is SYNTHETIC and exists only inside tests - it is never exported."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone


class FakeResponse:
    def __init__(self, status=200, payload=None, text=""):
        self.status_code = status
        self._payload = payload if payload is not None else {}
        self.text = text or str(payload)

    def json(self):
        return self._payload


def iso_days_ago(days: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")


def channel_resource(cid, name, subs, desc="", country=None, hidden=False):
    stats = {"viewCount": "100000", "videoCount": "50"}
    if hidden:
        stats["hiddenSubscriberCount"] = True
    else:
        stats["subscriberCount"] = str(subs)
    snippet = {"title": name, "description": desc, "customUrl": "@" + name.lower().replace(" ", "")}
    if country:
        snippet["country"] = country
    return {"id": cid, "snippet": snippet, "statistics": stats,
            "contentDetails": {"relatedPlaylists": {"uploads": "UU" + cid[2:]}},
            "brandingSettings": {"channel": {"keywords": ""}}}


def make_videos(cid, titles, views, likes, comments, first_days_ago=3):
    out = []
    for i, title in enumerate(titles):
        out.append({"id": f"{cid}_v{i}", "snippet": {"title": title, "description": title,
                                                      "publishedAt": iso_days_ago(first_days_ago + i * 7)},
                    "statistics": {"viewCount": str(views), "likeCount": str(likes), "commentCount": str(comments)}})
    return out


class FakeYouTube:
    """Routes requests.Session.get calls to canned YouTube API payloads."""

    def __init__(self, channels, videos):
        self.channels = {c["id"]: c for c in channels}
        self.videos = videos  # cid -> list of video resources
        self.calls = []

    def get(self, url, params=None, timeout=None, headers=None):
        endpoint = url.rsplit("/", 1)[-1]
        self.calls.append(endpoint)
        params = params or {}
        if endpoint == "search":
            return FakeResponse(payload={"items": [{"id": {"channelId": c}} for c in self.channels]})
        if endpoint == "channels":
            ids = params["id"].split(",")
            return FakeResponse(payload={"items": [self.channels[i] for i in ids if i in self.channels]})
        if endpoint == "playlistItems":
            cid = "UC" + params["playlistId"][2:]
            return FakeResponse(payload={"items": [{"contentDetails": {"videoId": v["id"]}}
                                                   for v in self.videos.get(cid, [])]})
        if endpoint == "videos":
            wanted = set(params["id"].split(","))
            items = [v for vs in self.videos.values() for v in vs if v["id"] in wanted]
            return FakeResponse(payload={"items": items})
        return FakeResponse(404, text="not found")
