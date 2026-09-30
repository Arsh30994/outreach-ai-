"""Public enrichment extraction and fetcher safety."""

from __future__ import annotations

import unittest

from outreach.services.email_extractor import extract_emails, is_valid_email
from outreach.services.enrichment import find_contact_email
from outreach.services.link_extractor import classify_urls, extract_urls
from outreach.services.website_fetcher import WebsiteFetcher
from tests.fixtures.youtube_fixtures import FakeResponse

NOT_FOUND = "Not Found"


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
        email, status, source = find_contact_email("no contact here", NOT_FOUND, None)
        self.assertEqual((email, status, source), (NOT_FOUND, NOT_FOUND, NOT_FOUND))

    def test_email_from_description(self):
        self.assertEqual(
            find_contact_email("contact: me@site.dev", NOT_FOUND, None)[0],
            "me@site.dev",
        )

    def test_email_from_website_contact_page(self):
        web = FakeWeb({"https://site.dev/contact": "<a href='mailto:biz@site.dev'>mail</a>"})
        email, status, source = find_contact_email("", "https://site.dev/", WebsiteFetcher(web))
        self.assertEqual(email, "biz@site.dev")
        self.assertTrue(source.startswith("http"))

    def test_robots_disallow(self):
        web = FakeWeb({"https://site.dev/": "a@site.dev"}, robots="User-agent: *\nDisallow: /")
        self.assertEqual(
            find_contact_email("", "https://site.dev/", WebsiteFetcher(web))[0],
            NOT_FOUND,
        )

    def test_private_hosts_never_fetched(self):
        web = FakeWeb({"http://127.0.0.1/": "a@b.com"})
        self.assertIsNone(WebsiteFetcher(web).fetch("http://127.0.0.1/"))
        self.assertEqual(web.calls, [])

    def test_url_classification(self):
        urls = extract_urls(
            "Site https://mysite.dev/ IG https://www.instagram.com/some.creator/ "
            "tt https://www.tiktok.com/@creator yt https://youtube.com/x"
        )
        website, ig, tt = classify_urls(urls)
        self.assertEqual(website, "https://mysite.dev/")
        self.assertEqual(ig, "https://www.instagram.com/some.creator/")
        self.assertEqual(tt, "https://www.tiktok.com/@creator")

    def test_email_validation(self):
        self.assertTrue(is_valid_email("a@b.co"))
        self.assertFalse(is_valid_email("Not Found"))


if __name__ == "__main__":
    unittest.main()
