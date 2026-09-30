"""Text cleanup and niche term matching with word/phrase boundaries."""

from __future__ import annotations

import re
import unicodedata
from typing import List
from urllib.parse import urlparse


_URL_RE = re.compile(r"https?://\S+|www\.\S+", re.IGNORECASE)
_WS_RE = re.compile(r"\s+")


def normalize_text(text: str) -> str:
    value = unicodedata.normalize("NFKC", text or "")
    value = _URL_RE.sub(" ", value)
    value = value.lower()
    value = _WS_RE.sub(" ", value).strip()
    return value


def term_pattern(term: str) -> re.Pattern[str]:
    cleaned = term.strip().lower()
    if " " in cleaned:
        parts = [re.escape(p) for p in cleaned.split()]
        return re.compile(r"(?<![A-Za-z0-9])" + r"\s+".join(parts) + r"(?![A-Za-z0-9])", re.I)
    return re.compile(r"(?<![A-Za-z0-9])" + re.escape(cleaned) + r"(?![A-Za-z0-9])", re.I)


def matched_terms(text: str, terms: List[str]) -> List[str]:
    hay = normalize_text(text)
    return [t for t in terms if term_pattern(t).search(hay)]


def strip_urls(text: str) -> str:
    return _URL_RE.sub("", text or "").strip()


def hostname(url: str) -> str:
    return (urlparse(url).hostname or "").lower()
