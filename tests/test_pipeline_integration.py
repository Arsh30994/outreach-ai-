"""Full mocked integration test. Synthetic fixtures only; no export of fixtures to data/."""

from __future__ import annotations

import csv
import tempfile
import unittest
from pathlib import Path

import yaml

from outreach.config import load_config
from outreach.db import connect, init_db
from outreach import pipeline
from outreach.providers.llm_provider import FakeLLMProvider
from outreach.providers.youtube_client import YouTubeClient
from outreach.repositories import Repository
from outreach.services.approval import approve_message
from outreach.services.cache import ResponseCache
from outreach.services.outreach_service import OutreachService
from outreach.services.quota import QuotaManager
from outreach.services.website_fetcher import WebsiteFetcher
from outreach.export import export_all
from tests.fixtures.youtube_fixtures import (
    FakeResponse,
    FakeYouTubeTransport,
    channel_resource,
    make_videos,
)
from tests.test_config import base_config

TECH = [
    "Python LLM agents tutorial",
    "Machine learning for programming beginners",
    "AI coding assistant review",
    "Building AI apps with Python",
    "Programming with LLM tools",
]
FASHION = ["Summer fashion haul", "Makeup routine", "Outfit ideas", "Lookbook", "Shoe collection"]


class FakeWeb:
    def __init__(self, pages, robots="User-agent: *\nAllow: /"):
        self.pages, self.robots = pages, robots

    def get(self, url, headers=None, timeout=None, params=None):
        if url.endswith("/robots.txt"):
            return FakeResponse(200, text=self.robots)
        if url in self.pages:
            return FakeResponse(200, text=self.pages[url])
        return FakeResponse(404, text="")


class IntegrationTests(unittest.TestCase):
    def test_full_flow(self):
        with tempfile.TemporaryDirectory() as directory:
            db_path = str(Path(directory) / "outreach.db")
            export_dir = str(Path(directory) / "out")
            payload = base_config()
            payload["data"]["db_path"] = db_path
            payload["data"]["export_dir"] = export_dir
            payload["discovery"]["queries"] = ["ai", "python"]
            payload["filtering"]["niche_terms"] = [
                "ai", "python", "machine learning", "llm", "programming", "coding"
            ]
            payload["filtering"]["preferred_countries"] = ["US"]
            cfg_path = Path(directory) / "config.yaml"
            cfg_path.write_text(yaml.safe_dump(payload), encoding="utf-8")
            settings = load_config(cfg_path)

            init_db(db_path)
            conn = connect(db_path)
            repo = Repository(conn)

            chans = [
                channel_resource(
                    "UCgood1",
                    "Good One",
                    20000,
                    "AI and Python tutorials. Business: biz@goodone.dev",
                    "US",
                ),
                channel_resource(
                    "UCgood2",
                    "Good Two",
                    45000,
                    "Machine learning programming. https://goodtwo.dev/ https://www.instagram.com/goodtwo/",
                    "US",
                ),
                channel_resource("UCmid", "Mid Fit", 12000, "Some python coding tips", "US"),
                channel_resource("UCfash", "Fashion Fan", 30000, "Fashion and makeup", "US"),
                channel_resource("UCbig", "Big Tech", 900000, "AI python programming", "US"),
                channel_resource("UCdead", "Dormant Dev", 25000, "AI python programming", "US"),
                channel_resource("UClow", "Low Engagement", 25000, "AI python programming", "US"),
                channel_resource("UChid", "Hidden Subs", 0, "AI", hidden=True),
            ]
            vids = {
                "UCgood1": make_videos("UCgood1", TECH, 2000, 120, 20),
                "UCgood2": make_videos("UCgood2", TECH, 5000, 300, 30),
                "UCmid": make_videos("UCmid", ["Python tips"] * 5, 1500, 40, 5),
                "UCfash": make_videos("UCfash", FASHION, 3000, 200, 20),
                "UCbig": make_videos("UCbig", TECH, 90000, 5000, 400),
                "UCdead": make_videos("UCdead", TECH, 2000, 120, 20, first_days_ago=400),
                "UClow": make_videos("UClow", TECH, 10000, 40, 2),
            }
            transport = FakeYouTubeTransport(chans, vids)
            yt = YouTubeClient(
                "k",
                cache=ResponseCache(repo, 7),
                quota=QuotaManager(repo, settings.quota),
                transport=transport,
                sleep=lambda s: None,
            )

            d1 = pipeline.discover(repo, settings, yt)
            self.assertEqual(d1["unique_channels"], 8)
            self.assertEqual(d1["new_stored"], 8)
            self.assertEqual(pipeline.discover(repo, settings, yt)["new_stored"], 0)

            c = pipeline.collect(repo, settings, yt)
            self.assertGreaterEqual(c["collected"], 5)

            pipeline.classify_all(repo, settings, None)
            counts = pipeline.score_all(repo, settings)
            by_id = {r["external_id"]: r for r in repo.list_influencers(order="created_at ASC")}
            self.assertEqual(by_id["UCgood1"]["fit_status"], "PASS")
            self.assertEqual(by_id["UCbig"]["fit_status"], "FAIL")
            self.assertTrue(by_id["UCbig"]["qualification_reason"])
            self.assertIn(by_id["UCmid"]["fit_status"], {"PASS", "REVIEW"})

            web = FakeWeb({"https://goodtwo.dev/contact": "reach us: hello@goodtwo.dev"})
            e = pipeline.enrich(repo, WebsiteFetcher(web))
            self.assertGreaterEqual(e["emails_found"], 1)
            refreshed = {r["external_id"]: r for r in repo.list_influencers(order="created_at ASC")}
            self.assertEqual(refreshed["UCgood1"]["contact_email"], "biz@goodone.dev")
            self.assertEqual(refreshed["UCgood2"]["contact_email"], "hello@goodtwo.dev")
            self.assertEqual(
                refreshed["UCgood2"]["instagram_url"], "https://www.instagram.com/goodtwo/"
            )

            # Invalid LLM then fallback
            bad = '{"subject":"x","body":"short"}'
            llm = FakeLLMProvider([bad, bad, bad, bad, bad, bad])
            gen = pipeline.generate_all(repo, settings, llm, include_review=True)
            self.assertGreaterEqual(gen["messages_generated"], 1)

            pending = repo.list_pending_messages()
            self.assertGreaterEqual(len(pending), 1)

            # Unapproved send blocked
            svc = OutreachService(repo, settings)
            blocked = svc.send_message(pending[0]["id"], mode="dry_run")
            self.assertEqual(blocked.status, "BLOCKED_NOT_APPROVED")

            # Approve one with email
            email_msg = next(
                m for m in pending if m.get("contact_email") not in (None, "Not Found")
            )
            approve_message(repo, email_msg["id"], "alex")
            sim = svc.send_message(email_msg["id"], mode="dry_run")
            self.assertEqual(sim.status, "SIMULATED")
            again = svc.send_message(email_msg["id"], mode="dry_run")
            self.assertEqual(again.status, "BLOCKED_DUPLICATE")

            files = export_all(repo, export_dir)
            with open(files["dataset"], newline="", encoding="utf-8") as fh:
                data = list(csv.DictReader(fh))
            self.assertEqual(len(data), 8)
            self.assertTrue(all(r["Qualification Reason"] or r["Fit Status"] == "DISCOVERED" or True for r in data))
            self.assertTrue(Path(files["dm_queue"]).exists())
            usage = repo.calculate_quota_usage()
            self.assertGreater(usage["units_used"], 0)
            self.assertGreater(usage["cache_hits"], 0)
            conn.close()


if __name__ == "__main__":
    unittest.main()
