"""Niche / theme classification: LLM when available, transparent keyword fallback otherwise."""
from __future__ import annotations

import logging
import re
from collections import Counter
from typing import Any, Dict, List, Optional

from .config import Config
from .llm import LLM, LLMError, parse_json
from .scoring import matched_terms

log = logging.getLogger(__name__)

SYSTEM = ("You are an influencer research classifier. Use ONLY the information provided. "
          "Do not invent facts. Return ONLY valid JSON.")

PROMPT = """Analyze this YouTube creator and return JSON with exactly these keys:
"primary_niche" (short string), "secondary_niches" (list of up to 3 strings),
"content_themes" (list of 3-5 short phrases grounded in the video titles),
"content_style" (short string, e.g. "Educational / technical"),
"audience_type" (short string describing who the content appears to be for; write "Unknown" if unclear).

Channel: {name}
Description: {description}
Recent video titles:
{titles}
"""

STOPWORDS = set("""a an the and or of to in on for with from by at as is are be this that these those your you i we
my our how what why when where which who will can do does did not no yes it its into about over under up down out more
most best top new vs using use via part full course complete guide tutorial video videos learn learning make build
building beginners beginner episode ep""".split())


def _titles(videos: List[Dict[str, Any]], limit: int = 10) -> List[str]:
    return [v["title"] for v in videos[:limit] if v.get("title")]


def classify_offline(profile: Dict[str, Any], videos: List[Dict[str, Any]], cfg: Config) -> Dict[str, Any]:
    text = " ".join([profile.get("description") or "", profile.get("channel_keywords") or ""] + _titles(videos))
    hits = matched_terms(text, cfg.niche_terms)
    words = Counter(
        w for t in _titles(videos) for w in re.findall(r"[A-Za-z][A-Za-z+#.]{2,}", t.lower())
        if w not in STOPWORDS)
    frequent = [w for w, c in words.most_common(8) if c >= 2][:3]
    themes = list(dict.fromkeys(hits[:4] + frequent))[:5]
    return {
        "niche": cfg.niche_label if hits else "Unclassified",
        "content_themes": themes,
        "content_style": "Not determined (keyword fallback)",
        "audience_type": "Not determined (keyword fallback)",
        "classification_source": "keyword-fallback",
    }


def classify(profile: Dict[str, Any], videos: List[Dict[str, Any]], cfg: Config,
             llm: Optional[LLM] = None) -> Dict[str, Any]:
    if llm is not None:
        prompt = PROMPT.format(name=profile.get("name"), description=(profile.get("description") or "")[:800],
                               titles="\n".join(f"- {t}" for t in _titles(videos)))
        try:
            data = parse_json(llm.complete(SYSTEM, prompt, max_tokens=500))
            themes = [str(t) for t in data.get("content_themes", [])][:5]
            if data.get("primary_niche") and themes:
                secondary = [str(s) for s in data.get("secondary_niches", [])][:3]
                niche = str(data["primary_niche"])
                if secondary:
                    niche += " (" + ", ".join(secondary) + ")"
                return {"niche": niche, "content_themes": themes,
                        "content_style": str(data.get("content_style", "Unknown")),
                        "audience_type": str(data.get("audience_type", "Unknown")),
                        "classification_source": f"llm:{llm.name}"}
        except (LLMError, AttributeError, TypeError) as exc:
            log.warning("LLM classification failed for %s (%s); using fallback", profile.get("name"), exc)
    return classify_offline(profile, videos, cfg)
