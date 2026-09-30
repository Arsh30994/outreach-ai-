"""Validate grounded outreach email and DM drafts."""

from __future__ import annotations

import re
from typing import Any, Dict, List

EMAIL_WORDS = (60, 90)
DM_WORDS = (15, 30)
STOP = set(
    "this that with from your have will what about their there which would could should "
    "video videos tutorial guide learn using build make best part full".split()
)


def word_count(text: str) -> int:
    return len((text or "").split())


def grounding_tokens(facts: Dict[str, Any]) -> set[str]:
    text = " ".join(
        [facts.get("video") or "", facts.get("niche") or "", " ".join(facts.get("themes") or [])]
    ).lower()
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
    if re.search(r"\baudience (age|gender|geography|demographics)\b", text, re.I):
        problems.append("it claims unsupported audience demographics")
    return problems


def validate_email(data: Any, facts: Dict[str, Any]) -> List[str]:
    if not isinstance(data, dict) or not str(data.get("subject", "")).strip() or not str(
        data.get("body", "")
    ).strip():
        return ["JSON must contain non-empty 'subject' and 'body'"]
    return _common_problems(str(data["body"]), facts, *EMAIL_WORDS)


def validate_dm(data: Any, facts: Dict[str, Any]) -> List[str]:
    if not isinstance(data, dict) or not str(data.get("dm", "")).strip():
        return ["JSON must contain a non-empty 'dm'"]
    return _common_problems(str(data["dm"]), facts, *DM_WORDS)
