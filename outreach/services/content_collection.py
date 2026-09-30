"""Collect recent uploads via playlistItems + videos.list (never search.list)."""

from __future__ import annotations

import logging
from typing import Any, Dict

from outreach.config import Settings
from outreach.exceptions import QuotaExceeded, YouTubeAPIError
from outreach.providers.youtube_client import YouTubeClient
from outreach.repositories import Repository
from outreach.services.engagement import calculate_engagement
from outreach.services.normalization import normalize_video
from outreach.time_utils import utc_now_iso

log = logging.getLogger(__name__)


def collect(repo: Repository, settings: Settings, yt: YouTubeClient) -> Dict[str, int]:
    """Fetch recent videos and compute engagement for creators still needing collect."""
    done = failed = skipped = 0
    rows = repo.list_influencers("collected_at IS NULL", order="created_at ASC")
    for row in rows:
        playlist = row.get("uploads_playlist_id")
        followers = row.get("followers")
        in_range = (
            followers is not None
            and settings.discovery.min_followers <= followers <= settings.discovery.max_followers
        )
        if not playlist or not in_range:
            skipped += 1
            continue
        try:
            video_ids = yt.get_playlist_items(playlist, settings.discovery.recent_videos)
            items = yt.get_videos(video_ids) if video_ids else []
        except QuotaExceeded:
            log.warning("Quota budget reached during collect; rerun later.")
            break
        except YouTubeAPIError as exc:
            repo.record_error(row["id"], f"collect: {exc}")
            failed += 1
            continue

        videos = []
        for item in items:
            try:
                video = normalize_video(item, row["id"])
            except (ValueError, KeyError, TypeError) as exc:
                log.error("Skipping malformed video for %s: %s", row["id"], exc)
                continue
            repo.upsert_content_item(video)
            videos.append(video)

        videos.sort(key=lambda v: v.get("published_at") or "", reverse=True)
        eng = calculate_engagement(videos, max_videos=settings.discovery.recent_videos)
        repo.update_influencer(
            row["id"],
            {
                "engagement_rate": eng["rate"],
                "engagement_method": eng["method"],
                "engagement_sample_size": eng["sample_size"],
                "engagement_calculated_at": eng["calculated_at"],
                "last_upload_at": videos[0]["published_at"] if videos else None,
                "collected_at": utc_now_iso(),
                "last_error": None,
                "last_error_at": None,
            },
        )
        repo.add_field_provenance(
            row["id"],
            "engagement_rate",
            eng["rate"],
            "independently_calculated_public_engagement",
        )
        done += 1
    usage = repo.calculate_quota_usage()
    return {
        "collected": done,
        "failed": failed,
        "skipped": skipped,
        "quota_used": usage["units_used"],
    }
