import unittest

from outreach.config import Config
from outreach.engagement import calculate_engagement
from outreach.scoring import matched_terms, score_profile
from tests.helpers import iso_days_ago

TERMS = ["ai", "python", "machine learning", "llm", "programming"]


def cfg():
    return Config(niche_terms=TERMS, min_followers=5000, max_followers=100000, min_engagement=1.0,
                  max_inactive_days=90, pass_score=75, review_score=60, preferred_countries=["US"])


def vids(n=10, title="Python machine learning with LLM agents"):
    return [{"title": title, "description": "", "views": 1000, "likes": 50, "comments": 10} for _ in range(n)]


def profile(**kw):
    base = {"followers": 30000, "engagement_rate": 6.0, "engagement_sample_size": 10, "country": "US",
            "last_upload_at": iso_days_ago(5), "description": "AI and Python programming", "channel_keywords": "",
            "name": "Dev"}
    base.update(kw)
    return base


class EngagementTests(unittest.TestCase):
    def test_basic_rate(self):
        r = calculate_engagement([{"views": 1000, "likes": 40, "comments": 10}] * 4)
        self.assertEqual(r["rate"], 5.0)
        self.assertEqual(r["sample_size"], 4)

    def test_excludes_unusable_videos(self):
        r = calculate_engagement([{"views": 0, "likes": 1, "comments": 0}, {"views": 500, "likes": None, "comments": 1},
                                  {"views": 1000, "likes": 20, "comments": None}])
        self.assertEqual(r["sample_size"], 1)
        self.assertEqual(r["rate"], 2.0)

    def test_no_data_is_not_found(self):
        r = calculate_engagement([])
        self.assertIsNone(r["rate"])
        self.assertEqual(r["method"], "Not Found")


class ScoringTests(unittest.TestCase):
    def test_word_boundary_matching(self):
        self.assertEqual(matched_terms("fashion and rain gear", ["ai"]), [])
        self.assertEqual(matched_terms("The AI revolution", ["ai"]), ["ai"])

    def test_strong_profile_passes(self):
        res = score_profile(profile(), vids(), cfg())
        self.assertEqual(res.status, "PASS")
        self.assertGreaterEqual(res.score, 75)
        self.assertIn("engagement", res.breakdown)

    def test_out_of_range_fails_with_reason(self):
        res = score_profile(profile(followers=250000), vids(), cfg())
        self.assertEqual(res.status, "FAIL")
        self.assertIn("outside the micro-influencer range", res.reasons[0])

    def test_hidden_subscribers_fail(self):
        res = score_profile(profile(followers=None), vids(), cfg())
        self.assertEqual(res.status, "FAIL")

    def test_inactive_fails(self):
        res = score_profile(profile(last_upload_at=iso_days_ago(200)), vids(), cfg())
        self.assertEqual(res.status, "FAIL")
        self.assertIn("Inactive", res.reasons[0])

    def test_low_engagement_fails(self):
        res = score_profile(profile(engagement_rate=0.3), vids(), cfg())
        self.assertEqual(res.status, "FAIL")

    def test_off_niche_does_not_pass(self):
        res = score_profile(profile(description="fashion lookbook and makeup"),
                            vids(title="Summer fashion haul"), cfg())
        self.assertNotEqual(res.status, "PASS")

    def test_contact_email_does_not_affect_score(self):
        a = score_profile(profile(email="a@b.com"), vids(), cfg())
        b = score_profile(profile(email="Not Found"), vids(), cfg())
        self.assertEqual(a.score, b.score)


if __name__ == "__main__":
    unittest.main()
