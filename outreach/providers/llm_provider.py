"""Optional LLM provider. Anthropic when available; otherwise None."""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Optional, Protocol

from outreach.config import Settings
from outreach.exceptions import ValidationError
from outreach.logging_config import redact

log = logging.getLogger(__name__)


class LLMProvider(Protocol):
    name: str

    def complete(self, system: str, user: str, max_tokens: int = 700) -> str: ...


class AnthropicProvider:
    def __init__(self, api_key: str, model: str):
        try:
            import anthropic
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("The 'anthropic' package is not installed") from exc
        self._client = anthropic.Anthropic(api_key=api_key)
        self.model = model
        self.name = model

    def complete(self, system: str, user: str, max_tokens: int = 700) -> str:
        try:
            resp = self._client.messages.create(
                model=self.model,
                max_tokens=max_tokens,
                system=system,
                messages=[{"role": "user", "content": user}],
            )
        except Exception as exc:
            raise RuntimeError(redact(str(exc))) from exc
        return "".join(
            block.text for block in resp.content if getattr(block, "type", "") == "text"
        )


class FakeLLMProvider:
    """Test double. Pop replies in order."""

    def __init__(self, replies: list[str], name: str = "fake-model"):
        self.replies = list(replies)
        self.name = name
        self.calls = 0

    def complete(self, system: str, user: str, max_tokens: int = 700) -> str:
        self.calls += 1
        if not self.replies:
            return "garbage"
        return self.replies.pop(0)


def build_llm(settings: Settings) -> Optional[LLMProvider]:
    key = settings.anthropic_api_key.get_secret_value().strip()
    if not key:
        log.warning("ANTHROPIC_API_KEY not set: offline fallback will be used.")
        return None
    try:
        return AnthropicProvider(key, settings.anthropic_model)
    except Exception as exc:
        log.warning("LLM unavailable (%s): offline fallback will be used.", redact(str(exc)))
        return None


def parse_json(text: str) -> Any:
    cleaned = re.sub(r"^```(?:json)?|```$", "", (text or "").strip(), flags=re.MULTILINE).strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        start, end = cleaned.find("{"), cleaned.rfind("}")
        if start != -1 and end > start:
            try:
                return json.loads(cleaned[start : end + 1])
            except json.JSONDecodeError:
                pass
    raise ValidationError("Model did not return valid JSON")
