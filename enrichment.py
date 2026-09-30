"""Contact enrichment from PUBLIC sources only (channel description + linked websites).

Emails are never guessed or generated. If nothing is found the value is "Not Found".
"""
from __future__ import annotations

import ipaddress
import logging
import re
from typing import Dict, List, Optional, Tuple
from urllib import robotparser
from urllib.parse import urljoin, urlparse

import requests

log = logging.getLogger(__name__)

NOT_FOUND = "Not Found"
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9\-]+(?:\.[A-Za-z0-9\-]+)*\.[A-Za-z]{2,}")
URL_RE = re.compile(r"https?://[^\s<>\"')\]]+", re.IGNORECASE)
IG_RE = re.compile(r"https?://(?:www\.)?instagram\.com/([A-Za-z0-9._]+)/?", re.IGNORECASE)

BAD_EMAIL_DOMAINS = {"example.com", "example.org", "domain.com", "email.com", "yourdomain.com",
                     "sentry.io", "wixpress.com", "sentry-next.wixpress.com"}
BAD_EMAIL_SUFFIXES = (".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".css", ".js")
SKIP_SITE_DOMAINS = ("youtube.com", "youtu.be", "instagram.com", "twitter.com", "x.com", "facebook.com",
                     "fb.com", "tiktok.com", "discord.gg", "discord.com", "twitch.tv", "linkedin.com",
                     "t.me", "wa.me", "amzn.to", "amazon.com", "bit.ly", "github.com")
IG_NON_PROFILE = {"p", "reel", "reels", "explore", "accounts", "stories", "tv"}


def extract_emails(text: str) -> List[str]:
    seen: Dict[str, None] = {}
    for m in EMAIL_RE.findall(text or ""):
        email = m.strip(".,;:").lower()
        domain = email.rsplit("@", 1)[-1]
        if domain in BAD_EMAIL_DOMAINS or email.endswith(BAD_EMAIL_SUFFIXES):
            continue
        seen.setdefault(email, None)
    return list(seen)


def is_valid_email(value: Optional[str]) -> bool:
    return bool(value) and value != NOT_FOUND and bool(re.fullmatch(EMAIL_RE.pattern, value))


def extract_urls(text: str) -> List[str]:
    urls = [u.rstrip(".,;:!?") for u in URL_RE.findall(text or "")]
    return list(dict.fromkeys(urls))


def classify_urls(urls: List[str]) -> Tuple[str, str]:
    """Return (website, instagram_url) found in a list of URLs; 'Not Found' when absent."""
    website, instagram = NOT_FOUND, NOT_FOUND
    for url in urls:
        m = IG_RE.match(url)
        if m:
            if instagram == NOT_FOUND and m.group(1).lower() not in IG_NON_PROFILE:
                instagram = f"https://www.instagram.com/{m.group(1)}/"
            continue
        host = (urlparse(url).hostname or "").lower()
        if website == NOT_FOUND and host and not any(host == d or host.endswith("." + d) for d in SKIP_SITE_DOMAINS):
            website = url
    return website, instagram


def _is_public_host(host: Optional[str]) -> bool:
    """Basic SSRF guard: never fetch localhost / private-IP literals from creator-supplied links."""
    if not host or host.lower() in {"localhost", "localhost.localdomain"}:
        return False
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return True
    return not (ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved)


class PageFetcher:
    """Polite fetcher: honours robots.txt, small timeouts, size cap, public hosts only."""

    def __init__(self, session: Optional[requests.Session] = None,
                 user_agent: str = "InfluencerOutreachBot/1.0 (research prototype)",
                 timeout: int = 10, max_bytes: int = 500_000):
        self.session = session or requests.Session()
        self.user_agent = user_agent
        self.timeout = timeout
        self.max_bytes = max_bytes
        self._robots: Dict[str, Optional[robotparser.RobotFileParser]] = {}

    def _robots_for(self, url: str) -> Optional[robotparser.RobotFileParser]:
        parts = urlparse(url)
        origin = f"{parts.scheme}://{parts.netloc}"
        if origin in self._robots:
            return self._robots[origin]
        rp: Optional[robotparser.RobotFileParser] = robotparser.RobotFileParser()
        try:
            resp = self.session.get(origin + "/robots.txt", headers={"User-Agent": self.user_agent},
                                    timeout=self.timeout)
            if resp.status_code == 200:
                rp.parse(resp.text.splitlines())
            elif 400 <= resp.status_code < 500:
                rp.parse([])                      # no robots.txt => allowed
            else:
                rp = None                         # server error => be conservative
        except requests.RequestException:
            rp = None
        self._robots[origin] = rp
        return rp

    def allowed(self, url: str) -> bool:
        rp = self._robots_for(url)
        return bool(rp and rp.can_fetch(self.user_agent, url))

    def fetch(self, url: str) -> Optional[str]:
        parts = urlparse(url)
        if parts.scheme not in ("http", "https") or not _is_public_host(parts.hostname):
            return None
        if not self.allowed(url):
            log.info("robots.txt disallows %s", url)
            return None
        try:
            resp = self.session.get(url, headers={"User-Agent": self.user_agent}, timeout=self.timeout)
        except requests.RequestException as exc:
            log.info("fetch failed for %s: %s", url, exc)
            return None
        if resp.status_code != 200:
            return None
        return resp.text[: self.max_bytes]


def find_contact_email(description: str, website: str, fetcher: Optional[PageFetcher],
                       max_pages: int = 3) -> Tuple[str, str]:
    """Look for a public email. Returns (email, source) or ("Not Found", "Not Found")."""
    emails = extract_emails(description)
    if emails:
        return emails[0], "channel_description"
    if fetcher and website != NOT_FOUND:
        pages = list(dict.fromkeys([website, urljoin(website, "/contact"), urljoin(website, "/about")]))
        for page in pages[:max_pages]:
            html = fetcher.fetch(page)
            if not html:
                continue
            emails = extract_emails(html)
            if emails:
                return emails[0], f"website:{page}"
    return NOT_FOUND, NOT_FOUND


def enrich_profile(profile: Dict, fetcher: Optional[PageFetcher]) -> Dict:
    """Build the enrichment field updates for one influencer."""
    urls = extract_urls(profile.get("description") or "")
    website, instagram = classify_urls(urls)
    email, source = find_contact_email(profile.get("description") or "", website, fetcher)
    return {"email": email, "email_source": source, "website": website, "instagram_url": instagram,
            "audience_age": NOT_FOUND, "audience_gender": NOT_FOUND, "audience_geography": NOT_FOUND}
