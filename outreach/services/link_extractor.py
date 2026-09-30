"""Extract website / Instagram / TikTok URLs from public creator text."""

from __future__ import annotations

import re
from typing import List, Tuple
from urllib.parse import urlparse

NOT_FOUND = "Not Found"
URL_RE = re.compile(r"https?://[^\s<>\"')\]]+", re.IGNORECASE)
IG_RE = re.compile(r"https?://(?:www\.)?instagram\.com/([A-Za-z0-9._]+)/?", re.I)
TT_RE = re.compile(r"https?://(?:www\.)?tiktok\.com/@([A-Za-z0-9._]+)/?", re.I)

SKIP_SITE_DOMAINS = (
    "youtube.com", "youtu.be", "instagram.com", "twitter.com", "x.com", "facebook.com",
    "fb.com", "tiktok.com", "discord.gg", "discord.com", "twitch.tv", "linkedin.com",
    "t.me", "wa.me", "amzn.to", "amazon.com", "bit.ly", "github.com",
)
IG_NON_PROFILE = {"p", "reel", "reels", "explore", "accounts", "stories", "tv"}


def extract_urls(text: str) -> List[str]:
    urls = [u.rstrip(".,;:!?") for u in URL_RE.findall(text or "")]
    return list(dict.fromkeys(urls))


def classify_urls(urls: List[str]) -> Tuple[str, str, str]:
    """Return (website, instagram_url, tiktok_url)."""
    website, instagram, tiktok = NOT_FOUND, NOT_FOUND, NOT_FOUND
    for url in urls:
        ig = IG_RE.match(url)
        if ig:
            if instagram == NOT_FOUND and ig.group(1).lower() not in IG_NON_PROFILE:
                instagram = f"https://www.instagram.com/{ig.group(1)}/"
            continue
        tt = TT_RE.match(url)
        if tt:
            if tiktok == NOT_FOUND:
                tiktok = f"https://www.tiktok.com/@{tt.group(1)}"
            continue
        host = (urlparse(url).hostname or "").lower()
        if website == NOT_FOUND and host and not any(
            host == d or host.endswith("." + d) for d in SKIP_SITE_DOMAINS
        ):
            website = url
    return website, instagram, tiktok
