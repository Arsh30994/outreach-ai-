"""Pipeline status reporting."""

from __future__ import annotations

from typing import Any, Dict

from outreach.config import Settings
from outreach.db import database_status
from outreach.repositories import Repository


def collect_status(repo: Repository, settings: Settings) -> Dict[str, Any]:
    db = database_status(settings.data.db_path)
    usage = repo.calculate_quota_usage()
    counts = {
        "discovered": repo.count_influencers(),
        "pass": repo.count_influencers("fit_status = 'PASS'"),
        "review": repo.count_influencers("fit_status = 'REVIEW'"),
        "fail": repo.count_influencers("fit_status = 'FAIL'"),
        "emails_found": repo.count_influencers(
            "contact_email IS NOT NULL AND contact_email != 'Not Found'"
        ),
        "messages": repo.conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0],
        "pending_review": repo.conn.execute(
            "SELECT COUNT(*) FROM messages WHERE status = 'PENDING_REVIEW'"
        ).fetchone()[0],
        "approved": repo.conn.execute(
            "SELECT COUNT(*) FROM messages WHERE status = 'APPROVED'"
        ).fetchone()[0],
        "simulated": repo.conn.execute(
            "SELECT COUNT(*) FROM outreach WHERE status = 'SIMULATED'"
        ).fetchone()[0],
        "sent": repo.conn.execute(
            "SELECT COUNT(*) FROM outreach WHERE status = 'SENT'"
        ).fetchone()[0],
    }
    return {"database": db, "counts": counts, "quota": usage, "mode": settings.outreach_mode}


def print_status(repo: Repository, settings: Settings) -> None:
    data = collect_status(repo, settings)
    db = data["database"]
    print(f"Database: {db['path']}")
    print(f"Initialized: {'yes' if db['initialized'] else 'no'}")
    print(f"Schema version: {db['schema_version'] if db['schema_version'] is not None else 'none'}")
    print(f"Outreach mode: {data['mode']}")
    print(
        f"Follower range: {settings.discovery.min_followers}-{settings.discovery.max_followers}"
    )
    print(f"Cache TTL days: {settings.cache.ttl_days}")
    for key, value in data["counts"].items():
        print(f"{key}: {value}")
    print(f"quota units used: {data['quota']['units_used']}")
    print(f"search calls used: {data['quota']['search_calls_used']}")
    print(f"cache hits: {data['quota']['cache_hits']}")
