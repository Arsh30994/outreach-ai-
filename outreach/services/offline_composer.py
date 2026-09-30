"""Deterministic offline email/DM composer from normalized evidence only."""

from __future__ import annotations

import hashlib
from typing import Any, Dict, Tuple

from outreach.config import BrandSettings
from outreach.services.message_validation import DM_WORDS, EMAIL_WORDS, word_count


def _seed(key: str) -> int:
    return int(hashlib.sha1(key.encode()).hexdigest()[:8], 16)


def _trim_words(text: str, n: int) -> str:
    words = text.split()
    return text if len(words) <= n else " ".join(words[:n]).rstrip(",:;-") + "..."


def offline_email(facts: Dict[str, Any], brand: BrandSettings, key: str) -> Tuple[str, str]:
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
        cta = [
            "If that sounds interesting, reply and I will send the details.",
            "Would you be open to a quick chat? Just reply to this email.",
        ][(s // 12) % 2]
        sign = f"Best,\n{brand.sender_name}\n{brand.name}"
        extras = [brand.value_prop, "Happy to adapt the format to whatever suits your audience best."]
        parts = [opener, fit, offer]
        for extra in extras:
            candidate = " ".join(parts + [extra] + [cta, sign])
            if word_count(candidate) <= EMAIL_WORDS[1]:
                parts.append(extra)
        body = " ".join(parts + [cta]) + "\n\n" + sign
        if EMAIL_WORDS[0] <= word_count(body) <= EMAIL_WORDS[1]:
            break
        # Pad short bodies with value prop repetition-safe sentence.
        while word_count(body) < EMAIL_WORDS[0]:
            body = body.replace(
                "\n\n" + sign,
                " Looking forward to exploring a thoughtful collaboration together.\n\n" + sign,
                1,
            )
            if word_count(body) >= EMAIL_WORDS[0]:
                break
    subject = f"{theme} x {brand.name}: {brand.collaboration} idea"
    return subject, body


def offline_dm(facts: Dict[str, Any], brand: BrandSettings, key: str) -> str:
    s = _seed(key + "dm")
    name = facts["name"]
    theme = facts["themes"][0] if facts["themes"] else facts["niche"]
    for title_words in (7, 4, 2):
        video = _trim_words(facts["video"], title_words) if facts["video"] else theme
        dm = [
            f'Hi {name}! Enjoyed your video "{video}". {brand.name} would love to explore a {brand.collaboration} with you. Open to details?',
            f'Hey {name}, your {theme} content stood out, especially "{video}". We\'d love to discuss a {brand.collaboration} with {brand.name}. Interested?',
        ][s % 2]
        if DM_WORDS[0] <= word_count(dm) <= DM_WORDS[1]:
            return dm
        if word_count(dm) < DM_WORDS[0]:
            dm += " Happy to share details if useful."
            if DM_WORDS[0] <= word_count(dm) <= DM_WORDS[1]:
                return dm
    return dm
