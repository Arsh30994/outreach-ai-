"""Configuration parsing, environment overrides, and secret handling."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

import yaml

from outreach.config import load_config
from outreach.exceptions import ConfigError


SECRET = "AIzaSySUPERSECRETKEY1234567890ABCDEF"


def base_config() -> dict:
    return {
        "brand": {
            "name": "YourBrand",
            "product": "an AI-powered code review tool for developers",
            "value_prop": "It helps developers catch bugs faster with an exclusive free trial.",
            "collaboration": "sponsored tutorial",
            "compensation": "a flat-fee payment plus free product access",
            "sender_name": "Alex",
            "sender_email": "alex@yourbrand.example",
            "postal_address": "YourBrand Inc., 123 Example Street, City, Country",
        },
        "discovery": {
            "queries": ["artificial intelligence tutorial"],
            "max_results_per_query": 50,
            "pages_per_query": 1,
            "min_followers": 5000,
            "max_followers": 100000,
            "recent_videos": 10,
        },
        "filtering": {
            "niche_label": "Technology / AI",
            "niche_terms": ["AI", "python"],
            "preferred_countries": ["us"],
            "minimum_engagement_rate": 1.0,
            "recent_upload_days": 90,
            "pass_score": 75,
            "review_score": 60,
        },
        "quota": {
            "search_list": 100,
            "channels_list": 1,
            "playlist_items_list": 1,
            "videos_list": 1,
            "daily_budget": 10000,
            "safety_budget": 9000,
            "safety_margin": 1000,
            "search_calls_per_day": 100,
        },
        "cache": {"ttl_days": 7},
        "data": {"db_path": "data/outreach.db", "export_dir": "data"},
    }


class ConfigTests(unittest.TestCase):
    def setUp(self) -> None:
        self._saved = {
            key: os.environ.get(key)
            for key in (
                "YOUTUBE_API_KEY",
                "ANTHROPIC_API_KEY",
                "ANTHROPIC_MODEL",
                "OUTREACH_MODE",
                "SEND_TEST_EMAIL_TO",
                "GMAIL_CREDENTIALS_FILE",
                "GMAIL_TOKEN_FILE",
                "MIN_FOLLOWERS",
                "MAX_FOLLOWERS",
                "PAGES_PER_QUERY",
                "RECENT_UPLOAD_DAYS",
                "MIN_ENGAGEMENT_RATE",
                "QUOTA_SAFETY_BUDGET",
                "QUOTA_DAILY_BUDGET",
                "QUOTA_SAFETY_MARGIN",
                "CACHE_TTL_DAYS",
                "OUTREACH_DB_PATH",
                "OUTREACH_EXPORT_DIR",
            )
        }
        for key in self._saved:
            os.environ.pop(key, None)

    def tearDown(self) -> None:
        for key, value in self._saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    def write_config(self, directory: str, payload: dict | None = None, text: str | None = None) -> Path:
        path = Path(directory) / "config.yaml"
        if text is None:
            path.write_text(yaml.safe_dump(payload or base_config()), encoding="utf-8")
        else:
            path.write_text(text, encoding="utf-8")
        return path

    def test_repository_config_loads(self) -> None:
        settings = load_config("config.yaml")
        self.assertEqual(settings.discovery.min_followers, 5000)
        self.assertEqual(settings.discovery.max_followers, 100000)
        self.assertEqual(settings.discovery.max_results_per_query, 50)
        self.assertEqual(settings.discovery.pages_per_query, 1)
        self.assertEqual(settings.filtering.minimum_engagement_rate, 1.0)
        self.assertEqual(settings.filtering.recent_upload_days, 90)
        self.assertEqual(settings.filtering.pass_score, 75)
        self.assertEqual(settings.filtering.review_score, 60)
        self.assertEqual(settings.brand.collaboration, "sponsored tutorial")
        self.assertEqual(settings.quota.search_list, 100)
        self.assertEqual(settings.quota.channels_list, 1)
        self.assertEqual(settings.quota.playlist_items_list, 1)
        self.assertEqual(settings.quota.videos_list, 1)
        self.assertEqual(settings.quota.daily_budget, 10000)
        self.assertEqual(settings.quota.safety_budget, 9000)
        self.assertEqual(settings.quota.safety_margin, 1000)
        self.assertEqual(settings.quota.search_calls_per_day, 100)
        self.assertEqual(settings.cache.ttl_days, 7)
        self.assertEqual(settings.outreach_mode, "dry_run")
        self.assertGreaterEqual(len(settings.discovery.queries), 1)

    def test_environment_overrides_and_normalization(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = self.write_config(directory)
            os.environ["MIN_FOLLOWERS"] = "8000"
            os.environ["CACHE_TTL_DAYS"] = "3"
            os.environ["OUTREACH_DB_PATH"] = str(Path(directory) / "local.db")
            os.environ["ANTHROPIC_MODEL"] = "claude-test-model"
            settings = load_config(path)
        self.assertEqual(settings.discovery.min_followers, 8000)
        self.assertEqual(settings.cache.ttl_days, 3)
        self.assertTrue(settings.data.db_path.endswith("local.db"))
        self.assertEqual(settings.anthropic_model, "claude-test-model")
        self.assertEqual(settings.filtering.niche_terms, ["ai", "python"])
        self.assertEqual(settings.filtering.preferred_countries, ["US"])

    def test_legacy_threshold_names_are_accepted(self) -> None:
        payload = base_config()
        payload["filtering"].pop("minimum_engagement_rate")
        payload["filtering"].pop("recent_upload_days")
        payload["filtering"]["min_engagement"] = 2.5
        payload["filtering"]["max_inactive_days"] = 30
        payload.pop("cache")
        payload["discovery"]["cache_ttl_days"] = 4
        with tempfile.TemporaryDirectory() as directory:
            path = self.write_config(directory, payload)
            settings = load_config(path)
        self.assertEqual(settings.filtering.minimum_engagement_rate, 2.5)
        self.assertEqual(settings.filtering.recent_upload_days, 30)
        self.assertEqual(settings.cache.ttl_days, 4)

    def test_missing_file(self) -> None:
        with self.assertRaises(ConfigError) as caught:
            load_config("missing-config.yaml")
        self.assertIn("Config file not found", str(caught.exception))

    def test_invalid_follower_range(self) -> None:
        payload = base_config()
        payload["discovery"]["min_followers"] = 200000
        payload["discovery"]["max_followers"] = 5000
        with tempfile.TemporaryDirectory() as directory:
            path = self.write_config(directory, payload)
            with self.assertRaises(ConfigError) as caught:
                load_config(path)
        self.assertIn("min_followers", str(caught.exception))

    def test_search_plan_over_safety_budget_fails(self) -> None:
        payload = base_config()
        payload["discovery"]["pages_per_query"] = 100
        with tempfile.TemporaryDirectory() as directory:
            path = self.write_config(directory, payload)
            with self.assertRaises(ConfigError) as caught:
                load_config(path)
        self.assertIn("safety budget", str(caught.exception))

    def test_test_mode_requires_recipient(self) -> None:
        os.environ["OUTREACH_MODE"] = "test"
        with tempfile.TemporaryDirectory() as directory:
            path = self.write_config(directory)
            with self.assertRaises(ConfigError) as caught:
                load_config(path)
        self.assertIn("SEND_TEST_EMAIL_TO", str(caught.exception))
        self.assertNotIn(SECRET, str(caught.exception))

    def test_live_mode_requires_gmail_paths(self) -> None:
        os.environ["OUTREACH_MODE"] = "live"
        with tempfile.TemporaryDirectory() as directory:
            path = self.write_config(directory)
            with self.assertRaises(ConfigError) as caught:
                load_config(path)
        self.assertIn("GMAIL_CREDENTIALS_FILE", str(caught.exception))

    def test_invalid_mode(self) -> None:
        os.environ["OUTREACH_MODE"] = "send-now"
        with tempfile.TemporaryDirectory() as directory:
            path = self.write_config(directory)
            with self.assertRaises(ConfigError) as caught:
                load_config(path)
        self.assertIn("outreach_mode", str(caught.exception))

    def test_secrets_stay_out_of_summary_and_errors(self) -> None:
        os.environ["YOUTUBE_API_KEY"] = SECRET
        os.environ["ANTHROPIC_API_KEY"] = "sk-ant-secretvalue123456"
        os.environ["OUTREACH_MODE"] = "nope"
        with tempfile.TemporaryDirectory() as directory:
            path = self.write_config(directory)
            with self.assertRaises(ConfigError) as caught:
                load_config(path)
        self.assertNotIn(SECRET, str(caught.exception))
        self.assertNotIn("sk-ant-secretvalue123456", str(caught.exception))

        os.environ["OUTREACH_MODE"] = "dry_run"
        with tempfile.TemporaryDirectory() as directory:
            path = self.write_config(directory)
            settings = load_config(path)
        rendered = f"{settings} {settings!r} {settings.safe_summary()} {settings.model_dump()}"
        self.assertNotIn(SECRET, rendered)
        self.assertNotIn("sk-ant-secretvalue123456", rendered)
        self.assertIn("youtube_api_key=set", settings.safe_summary())
        self.assertEqual(settings.require_youtube_api_key(), SECRET)

    def test_yaml_secrets_are_rejected_without_echoing_values(self) -> None:
        text = yaml.safe_dump(base_config()) + f"youtube_api_key: {SECRET}\n"
        with tempfile.TemporaryDirectory() as directory:
            path = self.write_config(directory, text=text)
            with self.assertRaises(ConfigError) as caught:
                load_config(path)
        self.assertIn("youtube_api_key", str(caught.exception))
        self.assertNotIn(SECRET, str(caught.exception))

    def test_missing_youtube_key_fails_clearly(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = self.write_config(directory)
            settings = load_config(path)
        with self.assertRaises(ConfigError) as caught:
            settings.require_youtube_api_key()
        self.assertIn("YOUTUBE_API_KEY is not set", str(caught.exception))

    def test_integer_override_rejects_non_integers(self) -> None:
        os.environ["MIN_FOLLOWERS"] = "five thousand"
        with tempfile.TemporaryDirectory() as directory:
            path = self.write_config(directory)
            with self.assertRaises(ConfigError) as caught:
                load_config(path)
        self.assertIn("MIN_FOLLOWERS must be an integer", str(caught.exception))
        self.assertNotIn("five thousand", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
