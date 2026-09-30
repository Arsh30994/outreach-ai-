"""Deterministic niche classification (keyword/heuristic). LLM wraps this later."""

from __future__ import annotations

from collections import Counter
from typing import Any, Dict, List, Optional

from outreach.config import Settings
from outreach.services.text_normalization import matched_terms, normalize_text
import re

CATEGORIES = {
    "artificial_intelligence": [
        "ai", "artificial intelligence", "machine learning", "deep learning", "llm",
        "generative ai", "neural network",
    ],
    "programming": ["python", "programming", "coding", "software engineering", "developer"],
    "developer_tools": ["developer tools", "code review", "ide", "devops", "api"],
    "cybersecurity": ["cybersecurity", "infosec", "hacking", "security"],
    "fintech": ["fintech", "crypto", "blockchain", "trading"],
    "design": ["ui design", "ux", "figma", "graphic design"],
    "gaming": ["gaming", "gameplay", "esports"],
    "lifestyle": ["lifestyle", "vlog", "fashion", "makeup", "travel"],
}

STOPWORDS = set("""a an the and or of to in on for with from by at as is are be this that these those your you i we
my our how what why when where which who will can do does did not no yes it its into about over under up down out more
most best top new vs using use via part full course complete guide tutorial video videos learn learning make build
building beginners beginner episode ep""".split())


def _titles(videos: List[Dict[str, Any]], limit: int = 10) -> List[str]:
    return [v["title"] for v in videos[:limit] if v.get("title")]


def classify_offline(
    profile: Dict[str, Any], videos: List[Dict[str, Any]], settings: Settings
) -> Dict[str, Any]:
    text = " ".join(
        [profile.get("description") or "", profile.get("channel_keywords") or "", profile.get("name") or ""]
        + _titles(videos)
    )
    category_hits: Dict[str, List[str]] = {}
    for category, terms in CATEGORIES.items():
        hits = matched_terms(text, terms)
        if hits:
            category_hits[category] = hits

    niche_hits = matched_terms(text, settings.filtering.niche_terms)
    ordered = sorted(category_hits.items(), key=lambda kv: (-len(kv[1]), kv[0]))
    primary = ordered[0][0] if ordered else "other"
    secondary = [name for name, _ in ordered[1:4]]
    words = Counter(
        w for t in _titles(videos)
        for w in re.findall(r"[A-Za-z][A-Za-z+#.]{2,}", normalize_text(t))
        if w not in STOPWORDS
    )
    frequent = [w for w, c in words.most_common(8) if c >= 2][:3]
    themes = list(dict.fromkeys(niche_hits[:4] + frequent))[:5]
    evidence = [f"term:{t}" for t in niche_hits[:8]]
    confidence = min(1.0, 0.25 * len(niche_hits) + 0.1 * len(themes))
    niche_label = settings.filtering.niche_label if niche_hits else primary
    return {
        "niche": niche_label,
        "primary_niche": primary,
        "secondary_niches": secondary,
        "content_themes": themes,
        "content_style": "Not determined (keyword fallback)",
        "audience_type": "Not determined (keyword fallback)",
        "evidence": evidence,
        "confidence": confidence,
        "classification_source": "keyword-fallback",
        "matching_evidence": evidence,
    }
