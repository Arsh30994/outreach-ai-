"""Resumable, idempotent pipeline stages."""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, Optional

from outreach.config import Settings
from outreach.providers.llm_provider import LLMProvider
from outreach.providers.youtube_client import YouTubeClient
from outreach.repositories import Repository
from outreach.services.classification import classify_offline
from outreach.services.content_collection import collect as collect_content
from outreach.services.discovery import discover as discover_channels
from outreach.services.enrichment import enrich_all
from outreach.services.instagram_queue import enqueue_from_message
from outreach.services.llm_classification import classify_creator
from outreach.services.personalization import generate_messages
from outreach.services.scoring import score_profile
from outreach.services.website_fetcher import WebsiteFetcher
from outreach.time_utils import utc_now_iso

log = logging.getLogger(__name__)


def discover(repo: Repository, settings: Settings, yt: YouTubeClient) -> Dict[str, Any]:
    return discover_channels(repo, settings, yt)


def collect(repo: Repository, settings: Settings, yt: YouTubeClient) -> Dict[str, Any]:
    return collect_content(repo, settings, yt)


def classify_all(
    repo: Repository, settings: Settings, llm: Optional[LLMProvider] = None
) -> Dict[str, int]:
    n = failed = 0
    for row in repo.list_influencers(
        "collected_at IS NOT NULL AND classified_at IS NULL", order="created_at ASC"
    ):
        try:
            videos = repo.list_content(row["id"], limit=settings.discovery.recent_videos)
            result = classify_creator(row, videos, settings, llm)
            repo.update_influencer(
                row["id"],
                {
                    "niche": result.get("niche"),
                    "content_themes": result.get("content_themes") or [],
                    "content_style": result.get("content_style"),
                    "audience_type": result.get("audience_type"),
                    "classification_source": result.get("classification_source"),
                    "classified_at": utc_now_iso(),
                    "last_error": None,
                },
            )
            n += 1
        except Exception as exc:
            repo.record_error(row["id"], f"classify: {exc}")
            failed += 1
    return {"classified": n, "failed": failed}


def score_all(repo: Repository, settings: Settings, rescore: bool = True) -> Dict[str, int]:
    counts = {"PASS": 0, "REVIEW": 0, "FAIL": 0, "failed": 0}
    where = "1=1" if rescore else "scored_at IS NULL"
    for row in repo.list_influencers(where, order="created_at ASC"):
        try:
            videos = repo.list_content(row["id"], limit=settings.discovery.recent_videos)
            # Ensure offline classification fields exist for scoring text.
            if not row.get("niche"):
                offline = classify_offline(row, videos, settings)
                repo.update_influencer(
                    row["id"],
                    {
                        "niche": offline["niche"],
                        "content_themes": offline["content_themes"],
                        "content_style": offline["content_style"],
                        "audience_type": offline["audience_type"],
                        "classification_source": offline["classification_source"],
                    },
                )
                row.update(offline)
            result = score_profile(row, videos, settings)
            repo.update_influencer(
                row["id"],
                {
                    "fit_score": result.score,
                    "fit_status": result.fit_status,
                    "fit_components": result.components,
                    "fit_reasons": result.reasons,
                    "qualification_status": result.qualification_status,
                    "qualification_reason": result.qualification_reason,
                    "scored_at": utc_now_iso(),
                    "last_error": None,
                },
            )
            counts[result.fit_status] += 1
        except Exception as exc:
            repo.record_error(row["id"], f"score: {exc}")
            counts["failed"] += 1
    return counts


def enrich(repo: Repository, fetcher: Optional[WebsiteFetcher] = None) -> Dict[str, int]:
    return enrich_all(repo, fetcher or WebsiteFetcher())


def generate_all(
    repo: Repository,
    settings: Settings,
    llm: Optional[LLMProvider] = None,
    include_review: bool = True,
    force: bool = False,
) -> Dict[str, int]:
    statuses = ("PASS", "REVIEW") if include_review else ("PASS",)
    placeholders = ",".join("?" for _ in statuses)
    n = skipped = failed = 0
    for row in repo.list_influencers(
        f"fit_status IN ({placeholders}) AND enriched_at IS NOT NULL",
        statuses,
        order="fit_score DESC",
    ):
        if not force:
            pending = repo.conn.execute(
                """SELECT 1 FROM messages WHERE influencer_id = ?
                   AND status IN ('PENDING_REVIEW','APPROVED') LIMIT 1""",
                (row["id"],),
            ).fetchone()
            if pending:
                skipped += 1
                continue
        try:
            if force:
                repo.supersede_pending_for_influencer(row["id"])
            videos = repo.list_content(row["id"], limit=settings.discovery.recent_videos)
            msg = generate_messages(row, videos, settings, llm)
            message_id = repo.create_message(
                {
                    "influencer_id": row["id"],
                    "email_subject": msg["email_subject"],
                    "email_body": msg["email_body"],
                    "instagram_dm": msg["instagram_dm"],
                    "status": "PENDING_REVIEW",
                    "model": msg["model"],
                    "prompt_version": msg["prompt_version"],
                    "generation_method": msg["generation_method"],
                    "evidence_used": msg["evidence_used"],
                    "notes": msg["notes"],
                }
            )
            enqueue_from_message(repo, message_id)
            n += 1
        except Exception as exc:
            repo.record_error(row["id"], f"generate: {exc}")
            failed += 1
    return {"messages_generated": n, "skipped": skipped, "failed": failed}


def run_pipeline(
    repo: Repository,
    settings: Settings,
    yt: YouTubeClient,
    llm: Optional[LLMProvider],
    fetcher: Optional[WebsiteFetcher] = None,
) -> Dict[str, Any]:
    from outreach.export import export_all

    summary: Dict[str, Any] = {}
    summary["discover"] = discover(repo, settings, yt)
    summary["collect"] = collect(repo, settings, yt)
    summary["classify"] = classify_all(repo, settings, llm)
    summary["score"] = score_all(repo, settings)
    summary["enrich"] = enrich(repo, fetcher)
    summary["generate"] = generate_all(repo, settings, llm)
    summary["export"] = export_all(repo, settings.data.export_dir)
    return summary
