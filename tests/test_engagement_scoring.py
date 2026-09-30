"""Normalization, engagement, word-boundary matching, hard gates, fit scoring."""

from __future__ import annotations

import unittest

from outreach.config import load_config
from outreach.services.engagement import calculate_engagement
from outreach.services.normalization import normalize_channel
from outreach.services.scoring import score_profile
from outreach.services.text_normalization import matched_terms
from tests.fixtures.youtube_fixtures import channel_resource, iso_days_ago
from tests.test_config import base_config
import tempfile
from pathlib import Path
import yaml


def settings(**overrides):
    with tempfile.TemporaryDirectory() as directory:
        payload = base_config()
        payload["filtering"]["niche_terms"] = [
            "ai", "python", "machine learning", "llm", "programming"
        ]
        payload["filtering"]["preferred_countries"] = ["US"]
        path = Path(directory) / "c.yaml"
        path.write_text(yaml.safe_dump(payload), encoding="utf-8")
        cfg = load_config(path)
    for key, value in overrides.items():
        setattr(cfg.filtering, key, value) if hasattr(cfg.filtering, key) else None
    return cfg


def vids(n=10, title="Python machine learning with LLM agents"):
    return [
        {"title": title, "description": "", "views": 1000, "likes": 50, "comments": 10}
        for _ in range(n)
    ]


def profile(**kw):
    base = {
        "followers": 30000,
        "engagement_rate": 6.0,
        "engagement_sample_size": 10,
        "creator_country": "US",
        "last_upload_at": iso_days_ago(5),
        "description": "AI and Python programming",
        "channel_keywords": "",
        "name": "Dev",
        "contact_email": "Not Found",
    }
    base.update(kw)
    return base


class EngagementTests(unittest.TestCase):
    def test_basic_rate(self):
        r = calculate_engagement([{"views": 1000, "likes": 40, "comments": 10}] * 4)
        self.assertEqual(r["rate"], 5.0)
        self.assertEqual(r["sample_size"], 4)
        self.assertIn("independently_calculated", r["method"])

    def test_excludes_unusable_videos(self):
        r = calculate_engagement(
            [
                {"views": 0, "likes": 1, "comments": 0},
                {"views": 500, "likes": None, "comments": 1},
                {"views": 1000, "likes": 20, "comments": None},
            ]
        )
        self.assertEqual(r["sample_size"], 1)
        self.assertEqual(r["rate"], 2.0)

    def test_no_data_is_not_found(self):
        r = calculate_engagement([])
        self.assertIsNone(r["rate"])
        self.assertEqual(r["method"], "Not Found")

    def test_ten_video_maximum(self):
        many = [{"views": 1000, "likes": 10, "comments": 0} for _ in range(20)]
        r = calculate_engagement(many, max_videos=10)
        self.assertEqual(r["sample_size"], 10)


class NormalizationTests(unittest.TestCase):
    def test_subscriber_and_country(self):
        parsed = normalize_channel(channel_resource("UCx", "X", 12000, country="IN"))
        self.assertEqual(parsed["followers"], 12000)
        self.assertEqual(parsed["followers_source"], "api_reported")
        self.assertEqual(parsed["creator_country"], "IN")
        self.assertEqual(parsed["audience_geography"], "Not Found")
        self.assertEqual(parsed["id"], "yt_UCx")

    def test_hidden_subscribers(self):
        parsed = normalize_channel(channel_resource("UCx", "X", 0, hidden=True))
        self.assertIsNone(parsed["followers"])
        self.assertEqual(parsed["followers_hidden"], 1)


class ScoringTests(unittest.TestCase):
    def test_word_boundary_matching(self):
        self.assertEqual(matched_terms("fashion and rain gear", ["ai"]), [])
        self.assertEqual(matched_terms("The AI revolution", ["ai"]), ["ai"])
        self.assertEqual(matched_terms("machine learning basics", ["machine learning"]), ["machine learning"])

    def test_strong_profile_passes(self):
        res = score_profile(profile(), vids(), settings())
        self.assertEqual(res.fit_status, "PASS")
        self.assertGreaterEqual(res.score, 75)

    def test_out_of_range_fails(self):
        res = score_profile(profile(followers=250000), vids(), settings())
        self.assertEqual(res.qualification_status, "FAIL")
        self.assertEqual(res.failed_gate, "subscriber_range")

    def test_hidden_subscribers_fail(self):
        res = score_profile(profile(followers=None), vids(), settings())
        self.assertEqual(res.failed_gate, "hidden_subscribers")

    def test_inactive_fails(self):
        res = score_profile(profile(last_upload_at=iso_days_ago(200)), vids(), settings())
        self.assertEqual(res.failed_gate, "recent_upload")

    def test_low_engagement_fails(self):
        res = score_profile(profile(engagement_rate=0.3), vids(), settings())
        self.assertEqual(res.failed_gate, "minimum_engagement")

    def test_email_does_not_affect_score(self):
        a = score_profile(profile(contact_email="a@b.com"), vids(), settings())
        b = score_profile(profile(contact_email="Not Found"), vids(), settings())
        self.assertEqual(a.score, b.score)

    def test_component_maximums(self):
        res = score_profile(profile(), vids(), settings())
        totals = {k: v["max"] for k, v in res.components.items()}
        self.assertEqual(sum(totals.values()), 100)


if __name__ == "__main__":
    unittest.main()
