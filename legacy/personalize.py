"""Personalised email + Instagram DM generation with validation and retries.

Two separate prompts (email, DM). Drafts are validated in code (word counts, placeholders,
grounding in real channel facts) and regenerated with feedback when they fail. If no LLM is
available, a data-driven offline composer is used and the output is labelled `offline-fallback`.
"""
from __future__ import annotations

import hashlib
import logging
import re
from typing import Any, Callable, Dict, List, Optional, Tuple

from .config import Brand, Config
from .llm import LLM, LLMError, parse_json

log = logging.getLogger(__name__)

EMAIL_WORDS = (60, 90)
DM_WORDS = (15, 30)
MAX_ATTEMPTS = 3

EMAIL_SYSTEM = ("You are an influencer-outreach specialist writing on behalf of a brand. "
                "Write like a thoughtful human, never like a template. Never invent facts about the creator. "
                "Return ONLY valid JSON.")

EMAIL_PROMPT = """Write a personalised collaboration email.

Brand: {brand_name} - {product}
Value proposition: {value_prop}
Proposed collaboration: {collaboration} ({compensation})
Sender: {sender_name}

Creator facts (the ONLY facts you may use):
- Channel name: {name}
- Niche: {niche}
- Content themes: {themes}
- Content style: {style}
- Most recent video title: "{video}"

Rules:
- Body must be {lo}-{hi} words INCLUDING greeting and sign-off.
- Reference the recent video or a listed theme specifically. No generic compliments.
- State clearly that the collaboration is {compensation}; do not overpromise results.
- Do not claim to know their audience demographics, follower numbers or personal details.
- No placeholders such as [Name]. One clear call to action. Professional but human tone.

Return JSON: {{"subject": "...", "body": "..."}}"""

DM_SYSTEM = ("You write short, natural Instagram DMs for brand outreach. Never invent facts. "
             "Return ONLY valid JSON.")

DM_PROMPT = """Write a short Instagram DM to a creator.

Brand: {brand_name} ({product})
Proposed collaboration: {collaboration}
Creator facts (the ONLY facts you may use):
- Name: {name}
- Niche: {niche}
- Content themes: {themes}
- Most recent video title: "{video}"

Rules:
- {lo}-{hi} words total. Casual, friendly, specific to their content. No emojis spam (max one).
- Mention the brand and the collaboration idea. No placeholders.

Return JSON: {{"dm": "..."}}"""

STOP = set("this that with from your have will what about their there which would could should video videos "
           "tutorial guide learn using build make best part full".split())


# ---------------------------------------------------------------- facts & validation
def word_count(text: str) -> int:
    return len((text or "").split())


def _trim_words(text: str, n: int) -> str:
    words = text.split()
    return text if len(words) <= n else " ".join(words[:n]).rstrip(",:;-") + "..."


def build_facts(profile: Dict[str, Any], videos: List[Dict[str, Any]]) -> Dict[str, Any]:
    themes = profile.get("content_themes") or []
    return {
        "name": profile.get("name") or "there",
        "niche": profile.get("niche") or "your niche",
        "themes": themes,
        "style": profile.get("content_style") or "Unknown",
        "video": videos[0]["title"] if videos else "",
    }


def grounding_tokens(facts: Dict[str, Any]) -> set:
    text = " ".join([facts["video"], facts["niche"], " ".join(facts["themes"])]).lower()
    return {w for w in re.findall(r"[a-z][a-z+#]{3,}", text) if w not in STOP}


def _common_problems(text: str, facts: Dict[str, Any], lo: int, hi: int) -> List[str]:
    problems = []
    n = word_count(text)
    if not lo <= n <= hi:
        problems.append(f"it has {n} words but must have {lo}-{hi}")
    if re.search(r"\{\{|\[[^\]]*\]|<[^>]+>", text):
        problems.append("it contains a placeholder")
    tokens = grounding_tokens(facts)
    if tokens and not any(t in text.lower() for t in tokens):
        problems.append("it does not reference the creator's actual video or themes")
    return problems


def validate_email(data: Any, facts: Dict[str, Any]) -> List[str]:
    if not isinstance(data, dict) or not str(data.get("subject", "")).strip() or not str(data.get("body", "")).strip():
        return ["JSON must contain non-empty 'subject' and 'body'"]
    return _common_problems(str(data["body"]), facts, *EMAIL_WORDS)


def validate_dm(data: Any, facts: Dict[str, Any]) -> List[str]:
    if not isinstance(data, dict) or not str(data.get("dm", "")).strip():
        return ["JSON must contain a non-empty 'dm'"]
    return _common_problems(str(data["dm"]), facts, *DM_WORDS)


# ---------------------------------------------------------------- LLM path
def _ask(llm: LLM, system: str, prompt: str, validator: Callable[[Any], List[str]],
         notes: List[str], label: str) -> Optional[Dict[str, Any]]:
    feedback = ""
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            data = parse_json(llm.complete(system, prompt + feedback, max_tokens=600))
        except LLMError as exc:
            notes.append(f"{label} attempt {attempt}: {exc}")
            feedback = "\n\nYour previous reply was not valid JSON. Return ONLY the JSON object."
            continue
        problems = validator(data)
        if not problems:
            return data
        notes.append(f"{label} attempt {attempt}: " + "; ".join(problems))
        feedback = "\n\nYour previous draft was rejected because " + "; ".join(problems) + ". Fix this and return ONLY the JSON."
    return None


# ---------------------------------------------------------------- offline composer
def _seed(key: str) -> int:
    return int(hashlib.sha1(key.encode()).hexdigest()[:8], 16)


def offline_email(facts: Dict[str, Any], brand: Brand, key: str) -> Tuple[str, str]:
    s = _seed(key)
    name, niche = facts["name"], facts["niche"]
    theme = facts["themes"][0] if facts["themes"] else niche
    for title_words in (12, 7, 4):
        video = _trim_words(facts["video"], title_words) if facts["video"] else theme
        opener = [
            f'Hi {name}, your recent video "{video}" caught our attention.',
            f'Hello {name}, we came across "{video}" while looking at {niche} creators.',
            f'Hi {name}, "{video}" is exactly the kind of {theme} content we enjoy.',
        ][s % 3]
        fit = [
            f"Since your channel focuses on {theme}, we think {brand.name}, {brand.product}, could be genuinely useful to your viewers.",
            f"Your {theme} content looks like a natural match for {brand.name}, {brand.product}.",
        ][(s // 3) % 2]
        offer = [
            f"We would love to propose a {brand.collaboration} with {brand.compensation}, and you would keep full creative control.",
            f"We are offering a {brand.collaboration} with {brand.compensation}, plus complete freedom to share your honest opinion.",
        ][(s // 6) % 2]
        cta = ["If that sounds interesting, reply and I will send the details.",
               "Would you be open to a quick chat? Just reply to this email."][(s // 12) % 2]
        sign = f"Best,\n{brand.sender_name}\n{brand.name}"
        extras = [brand.value_prop, "Happy to adapt the format to whatever suits your audience best."]
        parts = [opener, fit, offer]
        for extra in extras:                           # add optional sentences while we stay within range
            candidate = " ".join(parts + [extra] + [cta, sign])
            if word_count(candidate) <= EMAIL_WORDS[1]:
                parts.append(extra)
        body = " ".join(parts + [cta]) + "\n\n" + sign
        if word_count(body) <= EMAIL_WORDS[1]:
            break
    subject = f"{theme} x {brand.name}: {brand.collaboration} idea"
    return subject, body


def offline_dm(facts: Dict[str, Any], brand: Brand, key: str) -> str:
    s = _seed(key + "dm")
    name = facts["name"]
    theme = facts["themes"][0] if facts["themes"] else facts["niche"]
    for title_words in (7, 4, 2):
        video = _trim_words(facts["video"], title_words) if facts["video"] else theme
        dm = [
            f'Hi {name}! Enjoyed your video "{video}". {brand.name} would love to explore a {brand.collaboration} with you. Open to details?',
            f'Hey {name}, your {theme} content stood out, especially "{video}". We\'d love to discuss a {brand.collaboration} with {brand.name}. Interested?',
        ][s % 2]
        if word_count(dm) <= DM_WORDS[1]:
            break
    return dm


# ---------------------------------------------------------------- public API
def generate_messages(profile: Dict[str, Any], videos: List[Dict[str, Any]], cfg: Config,
                      llm: Optional[LLM] = None) -> Dict[str, Any]:
    facts = build_facts(profile, videos)
    brand = cfg.brand
    key = profile.get("channel_id") or facts["name"]
    notes: List[str] = []
    used_llm = {"email": False, "dm": False}

    email = None
    if llm is not None:
        prompt = EMAIL_PROMPT.format(
            brand_name=brand.name, product=brand.product, value_prop=brand.value_prop,
            collaboration=brand.collaboration, compensation=brand.compensation, sender_name=brand.sender_name,
            name=facts["name"], niche=facts["niche"], themes=", ".join(facts["themes"]) or "n/a",
            style=facts["style"], video=facts["video"] or "n/a", lo=EMAIL_WORDS[0], hi=EMAIL_WORDS[1])
        email = _ask(llm, EMAIL_SYSTEM, prompt, lambda d: validate_email(d, facts), notes, "email")
        used_llm["email"] = email is not None
    if email is None:
        subject, body = offline_email(facts, brand, key)
        email = {"subject": subject, "body": body}
        if llm is not None:
            notes.append("email: fell back to offline composer")

    dm = None
    if llm is not None:
        prompt = DM_PROMPT.format(
            brand_name=brand.name, product=brand.product, collaboration=brand.collaboration,
            name=facts["name"], niche=facts["niche"], themes=", ".join(facts["themes"]) or "n/a",
            video=facts["video"] or "n/a", lo=DM_WORDS[0], hi=DM_WORDS[1])
        data = _ask(llm, DM_SYSTEM, prompt, lambda d: validate_dm(d, facts), notes, "dm")
        if data:
            dm, used_llm["dm"] = str(data["dm"]).strip(), True
    if dm is None:
        dm = offline_dm(facts, brand, key)
        if llm is not None:
            notes.append("dm: fell back to offline composer")

    model = f"llm:{llm.name}" if llm and all(used_llm.values()) else \
        "offline-fallback" if not any(used_llm.values()) else f"mixed:{getattr(llm, 'name', 'llm')}+offline-fallback"
    return {"email_subject": str(email["subject"]).strip(), "email_body": str(email["body"]).strip(),
            "instagram_dm": dm, "model": model, "notes": " | ".join(notes)}
