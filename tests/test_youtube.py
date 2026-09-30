"""YouTube client: cache, quota reservation, pagination, error classification."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from outreach.db import connect, init_db
from outreach.exceptions import PermanentYouTubeError, QuotaExceeded, TransientYouTubeError
from outreach.providers.youtube_client import YouTubeClient, _classify_http_error
from outreach.repositories import Repository
from outreach.services.cache import ResponseCache
from outreach.services.quota import QuotaManager
from outreach.config import QuotaSettings
from tests.fixtures.youtube_fixtures import FakeYouTubeTransport, channel_resource, make_videos


class YouTubeClientTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        path = str(Path(self.tmp.name) / "t.db")
        init_db(path)
        self.conn = connect(path)
        self.repo = Repository(self.conn)
        chan = channel_resource("UCaaa", "Alpha", 20000)
        self.transport = FakeYouTubeTransport(
            [chan], {"UCaaa": make_videos("UCaaa", ["a", "b", "c"], 1000, 50, 5)}
        )
        self.quota_settings = QuotaSettings(
            search_list=100,
            channels_list=1,
            playlist_items_list=1,
            videos_list=1,
            daily_budget=10000,
            safety_budget=9000,
            safety_margin=1000,
            search_calls_per_day=100,
        )

    def tearDown(self) -> None:
        self.conn.close()
        self.tmp.cleanup()

    def client(self, **kw) -> YouTubeClient:
        cache = ResponseCache(self.repo, ttl_days=7)
        quota = QuotaManager(self.repo, self.quota_settings)
        return YouTubeClient(
            "key",
            cache=cache,
            quota=quota,
            transport=self.transport,
            sleep=lambda s: None,
            **kw,
        )

    def test_cache_hit_does_not_reserve_quota(self) -> None:
        yt = self.client()
        yt.search_channels("ai")
        usage = self.repo.calculate_quota_usage()
        self.assertEqual(usage["units_used"], 100)
        yt.search_channels("ai")
        usage = self.repo.calculate_quota_usage()
        self.assertEqual(usage["units_used"], 100)
        self.assertEqual(usage["cache_hits"], 1)

    def test_search_pagination_consumes_quota_per_page(self) -> None:
        calls = {"n": 0}

        def paginated(endpoint, params):
            calls["n"] += 1
            if endpoint != "search":
                return self.transport.request(endpoint, params)
            if "pageToken" not in params:
                return {
                    "items": [{"id": {"channelId": "UCaaa"}}],
                    "nextPageToken": "PAGE2",
                }
            return {"items": [{"id": {"channelId": "UCbbb"}}]}

        yt = self.client()
        yt._request_fn = paginated
        ids = yt.search_channels("ai", pages=2)
        self.assertEqual([i["channel_id"] for i in ids], ["UCaaa", "UCbbb"])
        self.assertEqual(self.repo.calculate_quota_usage()["units_used"], 200)
        self.assertEqual(self.repo.calculate_quota_usage()["search_calls_used"], 2)

    def test_channel_and_video_batching(self) -> None:
        yt = self.client()
        vids = yt.get_playlist_items("UUaaa", 10)
        items = yt.get_videos(vids)
        self.assertEqual(len(items), 3)
        self.assertEqual(self.repo.calculate_quota_usage()["units_used"], 2)

    def test_local_budget_enforced(self) -> None:
        self.quota_settings.safety_budget = 50
        self.quota_settings.safety_margin = 9950
        with self.assertRaises(QuotaExceeded):
            self.client().search_channels("ai")

    def test_retries_transient_then_succeeds(self) -> None:
        state = {"n": 0}
        real = self.transport.request

        def flaky(endpoint, params):
            state["n"] += 1
            if state["n"] < 3:
                raise TransientYouTubeError("HTTP 503")
            return real(endpoint, params)

        yt = self.client()
        yt._request_fn = flaky
        self.assertEqual(yt.search_channels("ai")[0]["channel_id"], "UCaaa")

    def test_quota_exceeded_does_not_retry(self) -> None:
        def boom(endpoint, params):
            raise QuotaExceeded("YouTube API daily quota exhausted")

        yt = self.client()
        yt._request_fn = boom
        with self.assertRaises(QuotaExceeded):
            yt.search_channels("ai")

    def test_permanent_errors_classified(self) -> None:
        err = _classify_http_error(401, "invalid credentials")
        self.assertIsInstance(err, PermanentYouTubeError)
        err = _classify_http_error(403, '{"error":{"errors":[{"reason":"quotaExceeded"}]}}')
        self.assertIsInstance(err, QuotaExceeded)
        err = _classify_http_error(503, "busy")
        self.assertIsInstance(err, TransientYouTubeError)

    def test_duplicate_channel_ids_deduped_in_get_channels(self) -> None:
        yt = self.client()
        items = yt.get_channels(["UCaaa", "UCaaa", "UCaaa"])
        self.assertEqual(len(items), 1)
        self.assertEqual(len([c for c in self.transport.calls if c[0] == "channels"]), 1)


if __name__ == "__main__":
    unittest.main()
