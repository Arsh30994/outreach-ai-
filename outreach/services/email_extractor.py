"""Extract and validate publicly published email addresses. Never guess."""

from __future__ import annotations

import re
from typing import List, Optional

NOT_FOUND = "Not Found"
EMAIL_RE = re.compile(
    r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9\-]+(?:\.[A-Za-z0-9\-]+)*\.[A-Za-z]{2,}"
)
BAD_DOMAINS = {
    "example.com",
    "example.org",
    "domain.com",
    "email.com",
    "yourdomain.com",
    "sentry.io",
    "wixpress.com",
    "sentry-next.wixpress.com",
}
BAD_SUFFIXES = (".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".css", ".js")


def extract_emails(text: str) -> List[str]:
    seen: dict[str, None] = {}
    for match in EMAIL_RE.findall(text or ""):
        email = match.strip(".,;:").lower()
        domain = email.rsplit("@", 1)[-1]
        if domain in BAD_DOMAINS or email.endswith(BAD_SUFFIXES):
            continue
        if domain.endswith(BAD_SUFFIXES):
            continue
        seen.setdefault(email, None)
    return list(seen)


def is_valid_email(value: Optional[str]) -> bool:
    return bool(value) and value != NOT_FOUND and bool(re.fullmatch(EMAIL_RE.pattern, value))


def normalize_email(value: str) -> str:
    return value.strip().strip(".,;:").lower()
