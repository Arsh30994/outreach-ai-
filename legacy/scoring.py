"""Deterministic filtering and fit scoring. Every PASS/REVIEW/FAIL carries explicit reasons.

Score (100 points):
  audience_size       20  inside the micro range (full points in the sweet spot, reduced at the edges)
  niche_relevance     25  distinct niche terms found in channel description / keywords / video text
  content_relevance   20  share of recent videos that match niche terms
  engagement          20  calculated public engagement rate
  activity            10  recent upload cadence
  geography            5  declared channel country in the preferred list (0 if unknown)
Hard gates (automatic FAIL): hidden/out-of-range followers, no public videos, inactive, low engagement.
Contactability (email found) is deliberately NOT part of the fit score; it decides whether email can be sent.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .config import Config
from .engagement import days_since


@dataclass
class ScoreResult:
    score: int
    status: str                      # PASS | REVIEW | FAIL
    reasons: List[str] = field(default_factory=list)
    breakdown: Dict[str, Dict[str, Any]] = field(default_factory=dict)


def term_regex(term: str) -> re.Pattern:
    return re.compile(r"(?<![A-Za-z0-9])" + re.escape(term.lower()) + r"(?![A-Za-z0-9])", re.IGNORECASE)


def matched_terms(text: str, terms: List[str]) -> List[str]:
    return [t for t in terms if term_regex(t).search(text or "")]


def _size_points(followers: int, lo: int, hi: int) -> int:
    span = hi - lo
    if lo + 0.05 * span <= followers <= lo + 0.65 * span:
        return 20
    return 14


def _engagement_points(rate: Optional[float]) -> int:
    if rate is None:
        return 0
    for threshold, pts in ((5, 20), (3, 16), (2, 12), (1, 6)):
        if rate >= threshold:
            return pts
    return 0


def score_profile(profile: Dict[str, Any], videos: List[Dict[str, Any]], cfg: Config) -> ScoreResult:
    reasons: List[str] = []
    breakdown: Dict[str, Dict[str, Any]] = {}
    followers = profile.get("followers")

    # ---- hard gates ----
    gate_fail: List[str] = []
    if followers is None:
        gate_fail.append("Subscriber count is hidden or unavailable")
    elif not (cfg.min_followers <= followers <= cfg.max_followers):
        gate_fail.append(f"{followers:,} subscribers is outside the micro-influencer range "
                         f"({cfg.min_followers:,}-{cfg.max_followers:,})")
    if followers is not None and cfg.min_followers <= followers <= cfg.max_followers:
        if not videos:
            gate_fail.append("No public videos could be retrieved")
        else:
            idle = days_since(profile.get("last_upload_at"))
            if idle is not None and idle > cfg.max_inactive_days:
                gate_fail.append(f"Inactive: last upload {idle} days ago (limit {cfg.max_inactive_days})")
        rate = profile.get("engagement_rate")
        if videos and rate is not None and rate < cfg.min_engagement:
            gate_fail.append(f"Engagement {rate}% is below the {cfg.min_engagement}% minimum")
    if gate_fail:
        return ScoreResult(0, "FAIL", gate_fail, {})

    # ---- scoring ----
    pts = _size_points(followers, cfg.min_followers, cfg.max_followers)
    breakdown["audience_size"] = {"points": pts, "max": 20, "note": f"{followers:,} subscribers (API-reported)"}

    channel_text = " ".join([profile.get("description") or "", profile.get("channel_keywords") or "",
                             profile.get("name") or ""])
    video_text = " ".join((v.get("title") or "") + " " + (v.get("description") or "") for v in videos)
    terms = cfg.niche_terms
    channel_hits = set(matched_terms(channel_text, terms))
    all_hits = channel_hits | set(matched_terms(video_text, terms))
    niche_pts = round(25 * min(1.0, len(all_hits) / 4))
    breakdown["niche_relevance"] = {"points": niche_pts, "max": 25,
                                    "note": f"matched terms: {', '.join(sorted(all_hits)) or 'none'}"}

    relevant = sum(1 for v in videos if matched_terms((v.get("title") or "") + " " + (v.get("description") or ""), terms))
    ratio = relevant / len(videos)
    content_pts = round(20 * ratio)
    breakdown["content_relevance"] = {"points": content_pts, "max": 20,
                                      "note": f"{relevant}/{len(videos)} recent videos match niche terms"}

    rate = profile.get("engagement_rate")
    eng_pts = _engagement_points(rate)
    breakdown["engagement"] = {"points": eng_pts, "max": 20,
                               "note": f"{rate}% ({profile.get('engagement_sample_size', 0)} videos)"
                               if rate is not None else "Not Found - could not be calculated"}

    idle = days_since(profile.get("last_upload_at"))
    act_pts = 0 if idle is None else 10 if idle <= 30 else 7 if idle <= 60 else 4
    breakdown["activity"] = {"points": act_pts, "max": 10,
                             "note": "unknown" if idle is None else f"last upload {idle} days ago"}

    country = (profile.get("country") or "").upper()
    if cfg.preferred_countries and country in cfg.preferred_countries:
        geo_pts, geo_note = 5, f"declared channel country {country}"
    else:
        geo_pts, geo_note = 0, (f"declared channel country {country}" if country else "country not declared")
    breakdown["geography"] = {"points": geo_pts, "max": 5, "note": geo_note}

    total = sum(item["points"] for item in breakdown.values())
    if total >= cfg.pass_score:
        status = "PASS"
    elif total >= cfg.review_score:
        status = "REVIEW"
    else:
        status = "FAIL"
    reasons.append(f"Fit score {total}/100 ({status})")
    for name, item in breakdown.items():
        reasons.append(f"{name} {item['points']}/{item['max']}: {item['note']}")
    if not all_hits:
        reasons.append("No niche terms found in channel text or recent videos")
    return ScoreResult(total, status, reasons, breakdown)
