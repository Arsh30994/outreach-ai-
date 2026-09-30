"""End-to-end run on SYNTHETIC API payloads (tests only): discover -> ... -> send -> export."""
import csv
import tempfile
import unittest
from pathlib import Path

from outreach import db, pipeline
from outreach.config import Config
from outreach.enrichment import PageFetcher
from outreach.export import export_all
from outreach.sender import Outreach
from outreach.youtube import YouTubeClient
from tests.helpers import FakeYouTube, channel_resource, make_videos
from tests.test_enrichment_youtube import FakeWeb

TECH = ["Python LLM agents tutorial", "Machine learning for programming beginners", "AI coding assistant review",
        "Building AI apps with Python", "Programming with LLM tools"]
FASHION = ["Summer fashion haul", "Makeup routine", "Outfit ideas", "Lookbook", "Shoe collection"]


def build_world():
    chans = [
        channel_resource("UCgood1", "Good One", 20000, "AI and Python tutorials. Business: biz@goodone.dev", "US"),
        channel_resource("UCgood2", "Good Two", 45000, "Machine learning programming. https://goodtwo.dev/ https://www.instagram.com/goodtwo/", "US"),
        channel_resource("UCgood3", "Good Three", 8000, "LLM and AI coding videos", "GB"),
        channel_resource("UCfash", "Fashion Fan", 30000, "Fashion and makeup", "US"),
        channel_resource("UCbig", "Big Tech", 900000, "AI python programming", "US"),
        channel_resource("UCdead", "Dormant Dev", 25000, "AI python programming", "US"),
        channel_resource("UClow", "Low Engagement", 25000, "AI python programming", "US"),
        channel_resource("UChid", "Hidden Subs", 0, "AI", hidden=True),
    ]
    vids = {
        "UCgood1": make_videos("UCgood1", TECH, 2000, 120, 20),
        "UCgood2": make_videos("UCgood2", TECH, 5000, 300, 30),
        "UCgood3": make_videos("UCgood3", TECH, 1500, 90, 10),
        "UCfash": make_videos("UCfash", FASHION, 3000, 200, 20),
        "UCbig": make_videos("UCbig", TECH, 90000, 5000, 400),
        "UCdead": make_videos("UCdead", TECH, 2000, 120, 20, first_days_ago=400),
        "UClow": make_videos("UClow", TECH, 10000, 40, 2),
    }
    return chans, vids


class E2ETests(unittest.TestCase):
    def test_full_flow(self):
        conn = db.connect(":memory:")
        cfg = Config(dry_run=True, min_followers=5000, max_followers=100000,
                     niche_terms=["ai", "python", "machine learning", "llm", "programming", "coding"],
                     queries=["ai", "python"], preferred_countries=["US"])
        cfg.brand.name = "TestBrand"
        chans, vids = build_world()
        yt = YouTubeClient("k", cache=db.SQLiteCache(conn), session=FakeYouTube(chans, vids), sleep=lambda s: None)

        d = pipeline.discover(conn, cfg, yt)
        self.assertEqual(d["unique_channels"], 8)            # duplicates across queries collapsed
        self.assertEqual(d["new_stored"], 8)
        self.assertEqual(pipeline.discover(conn, cfg, yt)["new_stored"], 0)   # idempotent

        c = pipeline.collect(conn, cfg, yt)
        self.assertEqual(c["collected"], 6)                   # big and hidden-subscriber channels skipped
        pipeline.classify_all(conn, cfg, None)
        counts = pipeline.score_all(conn, cfg)
        status = {r["channel_id"]: r for r in db.query_influencers(conn)}
        for cid in ("UCgood1", "UCgood2", "UCgood3"):
            self.assertEqual(status[cid]["status"], "PASS", status[cid]["status_reason"])
        for cid in ("UCfash", "UCbig", "UCdead", "UClow", "UChid"):
            self.assertEqual(status[cid]["status"], "FAIL", cid)
            self.assertTrue(status[cid]["status_reason"])
        self.assertEqual(counts["PASS"], 3)

        web = FakeWeb({"https://goodtwo.dev/contact": "reach us: hello@goodtwo.dev"})
        e = pipeline.enrich_all(conn, cfg, PageFetcher(web))
        self.assertEqual(e, {"emails_found": 2, "emails_not_found": 1})
        self.assertEqual(status["UCgood3"]["email"], "Not Found")   # never guessed
        rows = {r["channel_id"]: r for r in db.query_influencers(conn)}
        self.assertEqual(rows["UCgood1"]["email"], "biz@goodone.dev")
        self.assertEqual(rows["UCgood2"]["email"], "hello@goodtwo.dev")
        self.assertEqual(rows["UCgood2"]["instagram_url"], "https://www.instagram.com/goodtwo/")

        self.assertEqual(pipeline.generate_all(conn, cfg, None)["messages_generated"], 3)
        self.assertEqual(pipeline.generate_all(conn, cfg, None)["messages_generated"], 0)  # not regenerated

        sender = Outreach(conn, cfg)
        ids = [r["id"] for r in db.query_influencers(conn, "status = 'PASS'")]
        self.assertEqual(sender.send_email(ids[0]).status, "BLOCKED_NOT_APPROVED")
        pipeline.approve(conn, ids)
        results = [sender.send_email(i).status for i in ids]
        self.assertEqual(sorted(results), ["SIMULATED", "SIMULATED", "SKIPPED_NO_EMAIL"])
        self.assertIn("BLOCKED_DUPLICATE", [sender.send_email(i).status for i in ids])

        with tempfile.TemporaryDirectory() as tmp:
            files = export_all(conn, tmp)
            with open(files["dataset"], newline="", encoding="utf-8") as fh:
                data = list(csv.DictReader(fh))
            self.assertEqual(len(data), 8)
            self.assertTrue(all(r["Status Reason"] for r in data))
            with open(files["tracker"], newline="", encoding="utf-8") as fh:
                tracker = list(csv.DictReader(fh))
            self.assertEqual(sum(r["Sent"] == "Simulated" for r in tracker), 2)
            self.assertTrue(Path(files["dm_queue"]).exists())


if __name__ == "__main__":
    unittest.main()
