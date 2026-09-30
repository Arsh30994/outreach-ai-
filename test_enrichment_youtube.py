import unittest

from outreach import db
from outreach.enrichment import (NOT_FOUND, PageFetcher, classify_urls, extract_emails, extract_urls,
                                 find_contact_email, is_valid_email)
from outreach.youtube import QuotaExceeded, YouTubeAPIError, YouTubeClient, parse_channel
from tests.helpers import FakeResponse, FakeYouTube, channel_resource, make_videos


class FakeWeb:
    def __init__(self, pages, robots="User-agent: *\nAllow: /"):
        self.pages, self.robots, self.calls = pages, robots, []

    def get(self, url, headers=None, timeout=None, params=None):
        self.calls.append(url)
        if url.endswith("/robots.txt"):
            return FakeResponse(200, text=self.robots)
        if url in self.pages:
            return FakeResponse(200, text=self.pages[url])
        return FakeResponse(404, text="")


class EnrichmentTests(unittest.TestCase):
    def test_extract_and_filter_emails(self):
        text = "Biz: Hello@Creator.io, logo@2x.png, test@example.com"
        self.assertEqual(extract_emails(text), ["hello@creator.io"])

    def test_no_guessing(self):
        email, source = find_contact_email("no contact here", NOT_FOUND, None)
        self.assertEqual((email, source), (NOT_FOUND, NOT_FOUND))

    def test_email_from_description(self):
        self.assertEqual(find_contact_email("contact: me@site.dev", NOT_FOUND, None),
                         ("me@site.dev", "channel_description"))

    def test_email_from_website_contact_page(self):
        web = FakeWeb({"https://site.dev/contact": "<a href='mailto:biz@site.dev'>mail</a>"})
        email, source = find_contact_email("", "https://site.dev/", PageFetcher(web))
        self.assertEqual(email, "biz@site.dev")
        self.assertTrue(source.startswith("website:"))

    def test_robots_disallow_is_respected(self):
        web = FakeWeb({"https://site.dev/": "a@site.dev"}, robots="User-agent: *\nDisallow: /")
        self.assertEqual(find_contact_email("", "https://site.dev/", PageFetcher(web)), (NOT_FOUND, NOT_FOUND))

    def test_private_hosts_never_fetched(self):
        web = FakeWeb({"http://127.0.0.1/": "a@b.com"})
        self.assertIsNone(PageFetcher(web).fetch("http://127.0.0.1/"))
        self.assertEqual(web.calls, [])

    def test_url_classification(self):
        urls = extract_urls("Site https://mysite.dev/ IG https://www.instagram.com/some.creator/ yt https://youtube.com/x")
        self.assertEqual(classify_urls(urls), ("https://mysite.dev/", "https://www.instagram.com/some.creator/"))

    def test_email_validation(self):
        self.assertTrue(is_valid_email("a@b.co"))
        self.assertFalse(is_valid_email("Not Found"))
        self.assertFalse(is_valid_email(None))


class YouTubeClientTests(unittest.TestCase):
    def setUp(self):
        self.conn = db.connect(":memory:")
        chan = channel_resource("UCaaa", "Alpha", 20000)
        self.fake = FakeYouTube([chan], {"UCaaa": make_videos("UCaaa", ["a", "b", "c"], 1000, 50, 5)})

    def client(self, **kw):
        return YouTubeClient("key", cache=db.SQLiteCache(self.conn), session=self.fake, sleep=lambda s: None, **kw)

    def test_parse_channel_hidden_subscribers(self):
        parsed = parse_channel(channel_resource("UCx", "X", 0, hidden=True))
        self.assertIsNone(parsed["followers"])
        self.assertEqual(parsed["followers_hidden"], 1)

    def test_quota_accounting_and_cache(self):
        yt = self.client()
        yt.search_channels("ai")
        self.assertEqual(yt.quota_used, 100)
        yt.search_channels("ai")                      # served from cache
        self.assertEqual(yt.quota_used, 100)
        self.assertEqual(yt.cache_hits, 1)

    def test_recent_videos_are_cheap(self):
        yt = self.client()
        vids = yt.get_recent_videos("UUaaa", 10)
        self.assertEqual(len(vids), 3)
        self.assertEqual(yt.quota_used, 2)

    def test_local_budget_enforced(self):
        yt = self.client(quota_budget=50)
        with self.assertRaises(QuotaExceeded):
            yt.search_channels("ai")

    def test_retries_then_succeeds(self):
        real_get, state = self.fake.get, {"n": 0}

        def flaky(url, params=None, timeout=None, headers=None):
            state["n"] += 1
            return FakeResponse(503, text="busy") if state["n"] < 3 else real_get(url, params, timeout)
        self.fake.get = flaky
        self.assertEqual(self.client().search_channels("ai"), ["UCaaa"])

    def test_quota_exceeded_response(self):
        self.fake.get = lambda *a, **k: FakeResponse(403, text='{"error":{"errors":[{"reason":"quotaExceeded"}]}}')
        with self.assertRaises(QuotaExceeded):
            self.client().search_channels("ai")

    def test_other_http_errors_raise(self):
        self.fake.get = lambda *a, **k: FakeResponse(400, text="bad request")
        with self.assertRaises(YouTubeAPIError):
            self.client().get_channels(["UCaaa"])


if __name__ == "__main__":
    unittest.main()
