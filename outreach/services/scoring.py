"""Hard gates and 100-point fit scoring. Email availability never affects fit_score."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from outreach.config import Settings
from outreach.services.engagement import days_since
from outreach.services.text_normalization import matched_terms


@dataclass
class ScoreResult:
    score: int
    fit_status: str
    qualification_status: str
    qualification_reason: str
    failed_gate: Optional[str] = None
    reasons: List[str] = field(default_factory=list)
    components: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    risks: List[str] = field(default_factory=list)


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


def score_profile(
    profile: Dict[str, Any], videos: List[Dict[str, Any]], settings: Settings
) -> ScoreResult:
    followers = profile.get("followers")
    lo = settings.discovery.min_followers
    hi = settings.discovery.max_followers
    min_eng = settings.filtering.minimum_engagement_rate
    max_idle = settings.filtering.recent_upload_days

    if followers is None:
        reason = "Subscriber count is hidden or unavailable"
        return ScoreResult(0, "FAIL", "FAIL", reason, "hidden_subscribers", [reason])
    if not (lo <= followers <= hi):
        reason = (
            f"{followers:,} subscribers is outside the micro-influencer range "
            f"({lo:,}-{hi:,})"
        )
        return ScoreResult(0, "FAIL", "FAIL", reason, "subscriber_range", [reason])
    if not videos:
        reason = "No public videos could be retrieved"
        return ScoreResult(0, "FAIL", "FAIL", reason, "no_public_videos", [reason])
    idle = days_since(profile.get("last_upload_at"))
    if idle is not None and idle > max_idle:
        reason = f"Inactive: last upload {idle} days ago (limit {max_idle})"
        return ScoreResult(0, "FAIL", "FAIL", reason, "recent_upload", [reason])
    rate = profile.get("engagement_rate")
    if rate is not None and rate < min_eng:
        reason = f"Engagement {rate}% is below the {min_eng}% minimum"
        return ScoreResult(0, "FAIL", "FAIL", reason, "minimum_engagement", [reason])

    components: Dict[str, Dict[str, Any]] = {}
    pts = _size_points(followers, lo, hi)
    components["audience_size"] = {
        "points": pts,
        "max": 20,
        "note": f"{followers:,} subscribers (API-reported)",
    }

    channel_text = " ".join(
        [
            profile.get("description") or "",
            profile.get("channel_keywords") or "",
            profile.get("name") or "",
        ]
    )
    video_text = " ".join(
        (v.get("title") or "") + " " + (v.get("description") or "") for v in videos
    )
    terms = settings.filtering.niche_terms
    channel_hits = set(matched_terms(channel_text, terms))
    all_hits = channel_hits | set(matched_terms(video_text, terms))
    niche_pts = round(25 * min(1.0, len(all_hits) / 4))
    components["niche_relevance"] = {
        "points": niche_pts,
        "max": 25,
        "note": f"matched terms: {', '.join(sorted(all_hits)) or 'none'}",
    }

    relevant = sum(
        1
        for v in videos
        if matched_terms((v.get("title") or "") + " " + (v.get("description") or ""), terms)
    )
    ratio = relevant / len(videos)
    content_pts = round(20 * ratio)
    components["content_relevance"] = {
        "points": content_pts,
        "max": 20,
        "note": f"{relevant}/{len(videos)} recent videos match niche terms",
    }

    eng_pts = _engagement_points(rate)
    components["engagement"] = {
        "points": eng_pts,
        "max": 20,
        "note": (
            f"{rate}% ({profile.get('engagement_sample_size', 0)} videos)"
            if rate is not None
            else "Not Found - could not be calculated"
        ),
    }

    act_pts = 0 if idle is None else 10 if idle <= 30 else 7 if idle <= 60 else 4
    components["activity"] = {
        "points": act_pts,
        "max": 10,
        "note": "unknown" if idle is None else f"last upload {idle} days ago",
    }

    country = (profile.get("creator_country") or "").upper()
    preferred = settings.filtering.preferred_countries
    if preferred and country in preferred:
        geo_pts, geo_note = 5, f"declared channel country {country}"
    else:
        geo_pts = 0
        geo_note = f"declared channel country {country}" if country else "country not declared"
    components["geography"] = {"points": geo_pts, "max": 5, "note": geo_note}

    total = sum(item["points"] for item in components.values())
    if total >= settings.filtering.pass_score:
        status = "PASS"
    elif total >= settings.filtering.review_score:
        status = "REVIEW"
    else:
        status = "FAIL"

    reasons = [f"Fit score {total}/100 ({status})"]
    for name, item in components.items():
        reasons.append(f"{name} {item['points']}/{item['max']}: {item['note']}")
    risks: List[str] = []
    if not all_hits:
        risks.append("No niche terms found in channel text or recent videos")
    if rate is None:
        risks.append("Engagement could not be calculated from public videos")
    if not country:
        risks.append("Creator country not declared")

    return ScoreResult(
        score=total,
        fit_status=status,
        qualification_status=status,
        qualification_reason="; ".join(reasons),
        failed_gate=None,
        reasons=reasons,
        components=components,
        risks=risks,
    )
