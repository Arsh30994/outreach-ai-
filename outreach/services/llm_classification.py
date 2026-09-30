"""Optional structured LLM classification and ranking with offline fallback."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, ValidationError as PydanticValidationError

from outreach.config import Settings
from outreach.exceptions import ValidationError
from outreach.providers.llm_provider import LLMProvider, parse_json
from outreach.services.classification import classify_offline

log = logging.getLogger(__name__)
PROMPTS = Path(__file__).resolve().parent.parent / "prompts"
PROMPT_VERSION = "classification-v1"
MAX_ATTEMPTS = 3


class ClassificationResult(BaseModel):
    primary_niche: str
    secondary_niches: List[str] = Field(default_factory=list)
    content_themes: List[str] = Field(default_factory=list)
    content_style: str = "Unknown"
    audience_type: str = "Unknown"
    evidence: List[str] = Field(default_factory=list)
    confidence: float = 0.0


class RankingResult(BaseModel):
    fit_label: str
    score_explanation: List[str] = Field(default_factory=list)
    supported_reasons: List[str] = Field(default_factory=list)
    risks_or_unknowns: List[str] = Field(default_factory=list)
    recommended_collaboration: str = ""
    confidence: float = 0.0


def _load_prompt(name: str) -> str:
    return (PROMPTS / name).read_text(encoding="utf-8")


def _titles(videos: List[Dict[str, Any]], limit: int = 10) -> List[str]:
    return [v["title"] for v in videos[:limit] if v.get("title")]


def classify_creator(
    profile: Dict[str, Any],
    videos: List[Dict[str, Any]],
    settings: Settings,
    llm: Optional[LLMProvider] = None,
) -> Dict[str, Any]:
    if llm is None:
        result = classify_offline(profile, videos, settings)
        result["prompt_version"] = PROMPT_VERSION
        result["model"] = "offline-fallback"
        return result

    system = "You are an influencer research classifier. Return ONLY valid JSON."
    prompt = _load_prompt("classification.txt").format(
        name=profile.get("name"),
        description=(profile.get("description") or "")[:800],
        titles="\n".join(f"- {t}" for t in _titles(videos)),
    )
    feedback = ""
    # Mark untrusted creator text boundary for the model.
    prompt = "UNTRUSTED_CREATOR_DATA_BEGIN\n" + prompt + "\nUNTRUSTED_CREATOR_DATA_END"
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            raw = parse_json(llm.complete(system, prompt + feedback, max_tokens=500))
            data = ClassificationResult.model_validate(raw)
            if not data.content_themes:
                raise ValidationError("content_themes must be non-empty")
            niche = data.primary_niche
            if data.secondary_niches:
                niche += " (" + ", ".join(data.secondary_niches[:3]) + ")"
            return {
                "niche": niche,
                "primary_niche": data.primary_niche,
                "secondary_niches": data.secondary_niches[:3],
                "content_themes": data.content_themes[:5],
                "content_style": data.content_style,
                "audience_type": data.audience_type,
                "evidence": data.evidence,
                "confidence": data.confidence,
                "classification_source": f"llm:{llm.name}",
                "prompt_version": PROMPT_VERSION,
                "model": llm.name,
            }
        except (ValidationError, PydanticValidationError, RuntimeError, TypeError, AttributeError) as exc:
            feedback = f"\n\nPrevious output failed validation: {exc}. Return ONLY valid JSON."
            log.warning("LLM classify attempt %d failed: %s", attempt, exc)
    result = classify_offline(profile, videos, settings)
    result["prompt_version"] = PROMPT_VERSION
    result["model"] = "offline-fallback"
    result["classification_source"] = "offline-fallback"
    return result


def rank_creator(
    profile: Dict[str, Any],
    settings: Settings,
    llm: Optional[LLMProvider] = None,
) -> Dict[str, Any]:
    """Explain an existing deterministic score. Never changes fit_score."""
    score = profile.get("fit_score")
    fallback = {
        "fit_label": profile.get("fit_status") or "UNKNOWN",
        "score_explanation": profile.get("fit_reasons") or [],
        "supported_reasons": profile.get("fit_reasons") or [],
        "risks_or_unknowns": [],
        "recommended_collaboration": settings.brand.collaboration,
        "confidence": 0.0,
        "model": "offline-fallback",
        "prompt_version": "ranking-v1",
        "deterministic_score": score,
    }
    if llm is None:
        return fallback
    prompt = _load_prompt("ranking.txt").format(
        brand_name=settings.brand.name,
        product=settings.brand.product,
        collaboration=settings.brand.collaboration,
        name=profile.get("name"),
        niche=profile.get("niche"),
        themes=", ".join(profile.get("content_themes") or []),
        score=score,
        components=profile.get("fit_components"),
        reasons=profile.get("fit_reasons"),
    )
    feedback = ""
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            raw = parse_json(llm.complete("Explain fit. JSON only.", prompt + feedback))
            data = RankingResult.model_validate(raw)
            return {
                **data.model_dump(),
                "model": llm.name,
                "prompt_version": "ranking-v1",
                "deterministic_score": score,
            }
        except (ValidationError, PydanticValidationError, RuntimeError) as exc:
            feedback = f"\n\nValidation error: {exc}. Return ONLY JSON."
    return fallback
