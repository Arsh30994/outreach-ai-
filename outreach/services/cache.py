"""SQLite-backed API response cache."""

from __future__ import annotations

from typing import Any, Optional

from outreach.repositories import Repository


class ResponseCache:
    def __init__(self, repo: Repository, ttl_days: int = 7):
        self.repo = repo
        self.ttl_days = ttl_days

    def get(self, cache_key: str) -> Optional[dict[str, Any]]:
        return self.repo.get_cached_response(cache_key)

    def set(self, cache_key: str, endpoint: str, payload: dict[str, Any]) -> None:
        self.repo.save_cached_response(cache_key, endpoint, payload, self.ttl_days)
