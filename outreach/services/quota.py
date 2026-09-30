"""YouTube quota reservation and accounting."""

from __future__ import annotations

from typing import Optional

from outreach.config import QuotaSettings
from outreach.exceptions import QuotaExceeded
from outreach.repositories import Repository


class QuotaManager:
    def __init__(self, repo: Repository, settings: QuotaSettings, discovery_run_id: Optional[int] = None):
        self.repo = repo
        self.settings = settings
        self.discovery_run_id = discovery_run_id

    def cost_for(self, endpoint: str) -> int:
        mapping = {
            "search": self.settings.search_list,
            "channels": self.settings.channels_list,
            "playlistItems": self.settings.playlist_items_list,
            "videos": self.settings.videos_list,
        }
        if endpoint not in mapping:
            raise ValueError(f"Unknown YouTube endpoint: {endpoint}")
        return mapping[endpoint]

    def usage(self) -> dict[str, int]:
        return self.repo.calculate_quota_usage()

    def reserve(self, endpoint: str) -> int:
        """Reserve quota units before an uncached request. Raises QuotaExceeded if unsafe."""
        cost = self.cost_for(endpoint)
        usage = self.usage()
        if usage["units_used"] + cost > self.settings.safety_budget:
            raise QuotaExceeded(
                f"Local safety budget of {self.settings.safety_budget} units would be exceeded"
            )
        if endpoint == "search" and usage["search_calls_used"] + 1 > self.settings.search_calls_per_day:
            raise QuotaExceeded(
                f"Daily search call limit of {self.settings.search_calls_per_day} would be exceeded"
            )
        self.repo.record_quota_event(
            endpoint,
            cost,
            reserved=True,
            search_call=(endpoint == "search"),
            cache_hit=False,
            discovery_run_id=self.discovery_run_id,
            detail="reserved",
        )
        return cost

    def record_cache_hit(self, endpoint: str) -> None:
        self.repo.record_quota_event(
            endpoint,
            0,
            reserved=False,
            search_call=False,
            cache_hit=True,
            discovery_run_id=self.discovery_run_id,
            detail="cache_hit",
        )
