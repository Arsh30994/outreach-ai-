"""Pipeline stages. Each stage is idempotent and resumable: it only touches rows that still need it,
and a failure on one influencer is recorded in `last_error` without stopping the batch."""
from __future__ import annotations

import logging
from typing import Dict, List, Optional

from . import db
from .classify import classify
from .config import Config
from .engagement import calculate_engagement
from .enrichment import PageFetcher, enrich_profile
from .llm import LLM
from .personalize import generate_messages
from .scoring import score_profile
from .youtube import QuotaExceeded, YouTubeAPIError, YouTubeClient

log = logging.getLogger(__name__)


def _in_range(row: Dict, cfg: Config) -> bool:
    f = row.get("followers")
    return f is not None and cfg.min_followers <= f <= cfg.max_followers


def discover(conn, cfg: Config, yt: YouTubeClient) -> Dict[str, int]:
    """Search -> dedupe -> batch channel stats -> store everything (filtering happens in `score`)."""
    found: List[str] = []
    for query in cfg.queries:
        try:
            ids = yt.search_channels(query, cfg.max_results_per_query, cfg.pages_per_query)
        except QuotaExceeded as exc:
            log.warning("Stopping discovery: %s", exc)
            break
        except YouTubeAPIError as exc:
            log.error("Search failed for %r: %s", query, exc)
            continue
        log.info("query %r -> %d channels", query, len(ids))
        found.extend(ids)
    unique = list(dict.fromkeys(found))
    known = {r["channel_id"] for r in db.query_influencers(conn)}
    new_ids = [c for c in unique if c not in known]
    stored = 0
    try:
        for ch in yt.get_channels(new_ids):
            db.upsert_influencer(conn, {**ch, "retrieved_at": db.now_iso()})
            stored += 1
    except YouTubeAPIError as exc:
        log.error("Channel lookup failed: %s", exc)
    return {"search_results": len(found), "unique_channels": len(unique), "new_stored": stored,
            "quota_used": yt.quota_used, "cache_hits": yt.cache_hits}


def collect(conn, cfg: Config, yt: YouTubeClient) -> Dict[str, int]:
    """Fetch recent videos + compute engagement for in-range channels only (saves quota)."""
    done = failed = 0
    for row in db.query_influencers(conn, "collected_at IS NULL"):
        if not _in_range(row, cfg) or not row.get("uploads_playlist"):
            continue
        try:
            videos = yt.get_recent_videos(row["uploads_playlist"], cfg.recent_videos)
        except QuotaExceeded:
            log.warning("Quota budget reached during collect; rerun later (cached work is kept).")
            break
        except YouTubeAPIError as exc:
            db.update_influencer(conn, row["id"], {"last_error": f"collect: {exc}"})
            failed += 1
            continue
        db.save_videos(conn, row["id"], videos)
        eng = calculate_engagement(videos)
        db.update_influencer(conn, row["id"], {
            "engagement_rate": eng["rate"], "engagement_method": eng["method"],
            "engagement_sample_size": eng["sample_size"],
            "last_upload_at": videos[0]["published_at"] if videos else None,
            "collected_at": db.now_iso(), "last_error": None})
        done += 1
    return {"collected": done, "failed": failed, "quota_used": yt.quota_used}


def classify_all(conn, cfg: Config, llm: Optional[LLM]) -> Dict[str, int]:
    n = 0
    for row in db.query_influencers(conn, "collected_at IS NOT NULL AND classified_at IS NULL"):
        videos = db.get_videos(conn, row["id"])
        result = classify(row, videos, cfg, llm)
        db.update_influencer(conn, row["id"], {**result, "classified_at": db.now_iso()})
        n += 1
    return {"classified": n}


def score_all(conn, cfg: Config, rescore: bool = True) -> Dict[str, int]:
    counts = {"PASS": 0, "REVIEW": 0, "FAIL": 0}
    where = "1=1" if rescore else "scored_at IS NULL"
    for row in db.query_influencers(conn, where):
        videos = db.get_videos(conn, row["id"])
        res = score_profile(row, videos, cfg)
        db.update_influencer(conn, row["id"], {
            "fit_score": res.score, "fit_breakdown": res.breakdown, "status": res.status,
            "status_reason": "; ".join(res.reasons), "scored_at": db.now_iso()})
        counts[res.status] += 1
    return counts


def enrich_all(conn, cfg: Config, fetcher: Optional[PageFetcher]) -> Dict[str, int]:
    """Enrich shortlisted (PASS/REVIEW) influencers only."""
    found = missing = 0
    for row in db.query_influencers(conn, "status IN ('PASS','REVIEW') AND enriched_at IS NULL"):
        try:
            fields = enrich_profile(row, fetcher)
        except Exception as exc:  # isolate per-row failures
            log.error("enrichment failed for %s: %s", row["name"], exc)
            db.update_influencer(conn, row["id"], {"last_error": f"enrich: {exc}"})
            continue
        db.update_influencer(conn, row["id"], {**fields, "enriched_at": db.now_iso()})
        found += fields["email"] != "Not Found"
        missing += fields["email"] == "Not Found"
    return {"emails_found": found, "emails_not_found": missing}


def generate_all(conn, cfg: Config, llm: Optional[LLM], include_review: bool = False, force: bool = False) -> Dict[str, int]:
    statuses = "('PASS','REVIEW')" if include_review else "('PASS')"
    n = 0
    for row in db.query_influencers(conn, f"status IN {statuses} AND enriched_at IS NOT NULL"):
        if not force and conn.execute("SELECT 1 FROM messages WHERE influencer_id = ?", (row["id"],)).fetchone():
            continue
        videos = db.get_videos(conn, row["id"])
        msg = generate_messages(row, videos, cfg, llm)
        conn.execute(
            """INSERT OR REPLACE INTO messages (influencer_id, email_subject, email_body, instagram_dm, model, notes,
                                                generated_at, approved, dm_status) VALUES (?,?,?,?,?,?,?,0,'MANUAL_REVIEW')""",
            (row["id"], msg["email_subject"], msg["email_body"], msg["instagram_dm"], msg["model"],
             msg["notes"], db.now_iso()))
        conn.commit()
        n += 1
    return {"messages_generated": n}


def approve(conn, inf_ids: List[str]) -> int:
    n = 0
    for inf_id in inf_ids:
        cur = conn.execute("UPDATE messages SET approved = 1, approved_at = ? WHERE influencer_id = ?",
                           (db.now_iso(), inf_id))
        n += cur.rowcount
    conn.commit()
    return n
