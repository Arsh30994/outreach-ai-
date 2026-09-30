"""Phase 2: SQLite persistence and repository constraints."""

from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from outreach.db import init_db, connect
from outreach.repositories import Repository


class RepositoryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = str(Path(self.tmp.name) / "t.db")
        init_db(self.db_path)
        self.conn = connect(self.db_path)
        self.repo = Repository(self.conn)

    def tearDown(self) -> None:
        self.conn.close()
        self.tmp.cleanup()

    def _influencer(self, cid: str = "UCaaa", name: str = "Alpha") -> str:
        return self.repo.upsert_influencer(
            {
                "external_id": cid,
                "name": name,
                "profile_url": f"https://www.youtube.com/channel/{cid}",
                "followers": 20000,
                "followers_source": "api_reported",
            }
        )

    def test_deduplication_by_platform_external_id(self) -> None:
        a = self._influencer("UCaaa", "Alpha")
        b = self.repo.upsert_influencer(
            {
                "external_id": "UCaaa",
                "name": "Alpha Updated",
                "profile_url": "https://www.youtube.com/channel/UCaaa",
                "followers": 21000,
                "followers_source": "api_reported",
            }
        )
        self.assertEqual(a, b)
        self.assertEqual(self.repo.count_influencers(), 1)
        self.assertEqual(self.repo.get_influencer(a)["name"], "Alpha Updated")

    def test_foreign_key_enforcement(self) -> None:
        with self.assertRaises(sqlite3.IntegrityError):
            self.repo.upsert_content_item(
                {
                    "influencer_id": "missing",
                    "external_id": "vid1",
                    "title": "t",
                    "url": "https://youtube.com/watch?v=vid1",
                }
            )

    def test_unique_idempotency_key(self) -> None:
        inf = self._influencer()
        self.repo.create_outreach_event(
            {
                "influencer_id": inf,
                "status": "FAILED",
                "idempotency_key": "key-1",
                "intended_recipient": "a@b.com",
            }
        )
        with self.assertRaises(sqlite3.IntegrityError):
            self.repo.create_outreach_event(
                {
                    "influencer_id": inf,
                    "status": "FAILED",
                    "idempotency_key": "key-1",
                    "intended_recipient": "a@b.com",
                }
            )

    def test_partial_unique_successful_outreach_by_influencer(self) -> None:
        inf = self._influencer()
        self.repo.create_outreach_event(
            {
                "influencer_id": inf,
                "status": "SIMULATED",
                "idempotency_key": "ok-1",
                "intended_recipient": "a@b.com",
            }
        )
        with self.assertRaises(sqlite3.IntegrityError):
            self.repo.create_outreach_event(
                {
                    "influencer_id": inf,
                    "status": "SENT",
                    "idempotency_key": "ok-2",
                    "intended_recipient": "a@b.com",
                }
            )

    def test_partial_unique_successful_outreach_by_email(self) -> None:
        a = self._influencer("UCa")
        b = self._influencer("UCb", "Beta")
        self.repo.create_outreach_event(
            {
                "influencer_id": a,
                "status": "SIMULATED",
                "idempotency_key": "mail-1",
                "intended_recipient": "Same@Example.com",
            }
        )
        with self.assertRaises(sqlite3.IntegrityError):
            self.repo.create_outreach_event(
                {
                    "influencer_id": b,
                    "status": "SIMULATED",
                    "idempotency_key": "mail-2",
                    "intended_recipient": "same@example.com",
                }
            )

    def test_cache_read_write(self) -> None:
        self.repo.save_cached_response("search:q", "search", {"items": [1]}, ttl_days=7)
        hit = self.repo.get_cached_response("search:q")
        self.assertEqual(hit, {"items": [1]})

    def test_quota_event_totals(self) -> None:
        self.repo.record_quota_event("search", 100, search_call=True)
        self.repo.record_quota_event("channels", 1)
        self.repo.record_quota_event("search", 0, cache_hit=True, reserved=False)
        usage = self.repo.calculate_quota_usage()
        self.assertEqual(usage["units_used"], 101)
        self.assertEqual(usage["search_calls_used"], 1)
        self.assertEqual(usage["cache_hits"], 1)

    def test_suppression(self) -> None:
        self.repo.add_suppression("email", "No@Mail.com", "opt-out")
        self.assertTrue(self.repo.is_suppressed("email", "no@mail.com"))
        self.assertFalse(self.repo.is_suppressed("email", "other@mail.com"))

    def test_init_db_is_idempotent(self) -> None:
        v1 = init_db(self.db_path)
        v2 = init_db(self.db_path)
        self.assertEqual(v1, 2)
        self.assertEqual(v2, 2)


if __name__ == "__main__":
    unittest.main()
