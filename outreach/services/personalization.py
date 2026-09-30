"""Grounded email + Instagram DM generation with validation and offline fallback."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from outreach.config import Settings
from outreach.exceptions import ValidationError
from outreach.providers.llm_provider import LLMProvider, parse_json
from outreach.services.message_validation import (
    DM_WORDS,
    EMAIL_WORDS,
    validate_dm,
    validate_email,
)
from outreach.services.offline_composer import offline_dm, offline_email

log = logging.getLogger(__name__)
PROMPTS = Path(__file__).resolve().parent.parent / "prompts"
PROMPT_VERSION = "personalization-v1"
MAX_ATTEMPTS = 3


def build_facts(profile: Dict[str, Any], videos: List[Dict[str, Any]]) -> Dict[str, Any]:
    themes = profile.get("content_themes") or []
    return {
        "name": profile.get("name") or "there",
        "niche": profile.get("niche") or "your niche",
        "themes": themes,
        "style": profile.get("content_style") or "Unknown",
        "video": videos[0]["title"] if videos else "",
    }


def _ask(llm: LLMProvider, system: str, prompt: str, validator, notes: List[str], label: str):
    feedback = ""
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            data = parse_json(llm.complete(system, prompt + feedback, max_tokens=600))
        except (ValidationError, RuntimeError) as exc:
            notes.append(f"{label} attempt {attempt}: {exc}")
            feedback = "\n\nYour previous reply was not valid JSON. Return ONLY the JSON object."
            continue
        problems = validator(data)
        if not problems:
            return data
        notes.append(f"{label} attempt {attempt}: " + "; ".join(problems))
        feedback = (
            "\n\nYour previous draft was rejected because "
            + "; ".join(problems)
            + ". Fix this and return ONLY the JSON."
        )
    return None


def generate_messages(
    profile: Dict[str, Any],
    videos: List[Dict[str, Any]],
    settings: Settings,
    llm: Optional[LLMProvider] = None,
) -> Dict[str, Any]:
    facts = build_facts(profile, videos)
    brand = settings.brand
    key = profile.get("external_id") or facts["name"]
    notes: List[str] = []
    used_llm = {"email": False, "dm": False}
    evidence_used = [
        f"name:{facts['name']}",
        f"niche:{facts['niche']}",
        *[f"theme:{t}" for t in facts["themes"]],
    ]
    if facts["video"]:
        evidence_used.append(f"video:{facts['video']}")

    email = None
    if llm is not None:
        prompt = (PROMPTS / "email.txt").read_text(encoding="utf-8").format(
            brand_name=brand.name,
            product=brand.product,
            value_prop=brand.value_prop,
            collaboration=brand.collaboration,
            compensation=brand.compensation,
            sender_name=brand.sender_name,
            name=facts["name"],
            niche=facts["niche"],
            themes=", ".join(facts["themes"]) or "n/a",
            style=facts["style"],
            video=facts["video"] or "n/a",
            lo=EMAIL_WORDS[0],
            hi=EMAIL_WORDS[1],
        )
        email = _ask(
            llm,
            "Outreach specialist. JSON only. Never invent facts.",
            prompt,
            lambda d: validate_email(d, facts),
            notes,
            "email",
        )
        used_llm["email"] = email is not None
    if email is None:
        subject, body = offline_email(facts, brand, key)
        email = {"subject": subject, "body": body}
        if llm is not None:
            notes.append("email: fell back to offline composer")

    dm = None
    if llm is not None:
        prompt = (PROMPTS / "dm.txt").read_text(encoding="utf-8").format(
            brand_name=brand.name,
            product=brand.product,
            collaboration=brand.collaboration,
            name=facts["name"],
            niche=facts["niche"],
            themes=", ".join(facts["themes"]) or "n/a",
            video=facts["video"] or "n/a",
            lo=DM_WORDS[0],
            hi=DM_WORDS[1],
        )
        data = _ask(
            llm,
            "Short Instagram DM writer. JSON only.",
            prompt,
            lambda d: validate_dm(d, facts),
            notes,
            "dm",
        )
        if data:
            dm, used_llm["dm"] = str(data["dm"]).strip(), True
    if dm is None:
        dm = offline_dm(facts, brand, key)
        if llm is not None:
            notes.append("dm: fell back to offline composer")

    if llm and all(used_llm.values()):
        method = f"llm:{llm.name}"
        generation_method = "llm"
    elif not any(used_llm.values()):
        method = "offline-fallback"
        generation_method = "offline-fallback"
    else:
        method = f"mixed:{getattr(llm, 'name', 'llm')}+offline-fallback"
        generation_method = "mixed"

    return {
        "email_subject": str(email["subject"]).strip(),
        "email_body": str(email["body"]).strip(),
        "instagram_dm": dm,
        "model": method,
        "generation_method": generation_method,
        "prompt_version": PROMPT_VERSION,
        "evidence_used": evidence_used,
        "notes": " | ".join(notes),
        "status": "PENDING_REVIEW",
    }
