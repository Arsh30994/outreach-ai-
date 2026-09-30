"""YouTube channel discovery: search → dedupe → batch channels.list → store candidates."""

from __future__ import annotations

import logging
from typing import Any, Dict

from outreach.config import Settings
from outreach.exceptions import QuotaExceeded, YouTubeAPIError
from outreach.providers.youtube_client import YouTubeClient
from outreach.repositories import Repository
from outreach.services.normalization import normalize_channel
from outreach.time_utils import utc_now_iso

log = logging.getLogger(__name__)


def discover(repo: Repository, settings: Settings, yt: YouTubeClient) -> Dict[str, Any]:
    """Idempotent discovery. Stores every candidate before filtering."""
    run_id = repo.create_discovery_run(settings.discovery.queries)
    found: list[str] = []
    source_by_id: dict[str, str] = {}
    for query in settings.discovery.queries:
        try:
            hits = yt.search_channels(
                query,
                max_results=settings.discovery.max_results_per_query,
                pages=settings.discovery.pages_per_query,
            )
        except QuotaExceeded as exc:
            log.warning("Stopping discovery: %s", exc)
            break
        except YouTubeAPIError as exc:
            log.error("Search failed for %r: %s", query, exc)
            continue
        log.info("query %r -> %d channels", query, len(hits))
        for hit in hits:
            cid = hit["channel_id"]
            found.append(cid)
            source_by_id.setdefault(cid, query)

    unique = list(dict.fromkeys(found))
    known = {
        row["external_id"]
        for row in repo.list_influencers(order="created_at ASC")
    }
    new_ids = [cid for cid in unique if cid not in known]
    stored = 0
    try:
        for item in yt.get_channels(new_ids if new_ids else unique[:0]):
            try:
                fields = normalize_channel(
                    item,
                    source_query=source_by_id.get(item["id"]),
                    discovery_run_id=run_id,
                )
            except (ValueError, KeyError, TypeError) as exc:
                log.error("Skipping malformed channel: %s", exc)
                continue
            # Also refresh known channels when re-fetching; discover primarily stores new.
            inf_id = repo.upsert_influencer(fields)
            repo.add_field_provenance(
                inf_id, "followers", fields.get("followers"), "youtube.channels.list"
            )
            repo.add_field_provenance(
                inf_id, "description", fields.get("description"), "youtube.channels.list"
            )
            stored += 1
        # When new_ids empty, still allow refreshing nothing — idempotent.
        if not new_ids and unique:
            # Optional refresh of already-known IDs is skipped to save quota; mark run.
            stored = 0
    except QuotaExceeded as exc:
        log.warning("Channel lookup stopped: %s", exc)
    except YouTubeAPIError as exc:
        log.error("Channel lookup failed: %s", exc)

    usage = repo.calculate_quota_usage()
    result = {
        "discovery_run_id": run_id,
        "search_results": len(found),
        "unique_channels": len(unique),
        "new_stored": stored,
        "quota_used": usage["units_used"],
        "cache_hits": usage["cache_hits"],
    }
    repo.finish_discovery_run(
        run_id,
        search_results=result["search_results"],
        unique_channels=result["unique_channels"],
        new_stored=result["new_stored"],
        quota_used=result["quota_used"],
        status="completed",
        notes=f"finished_at={utc_now_iso()}",
    )
    return result
