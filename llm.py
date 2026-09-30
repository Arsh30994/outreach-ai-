"""Thin LLM abstraction. The pipeline works without a key (clearly labelled offline fallback)."""
from __future__ import annotations

import json
import logging
import re
from typing import Any, Optional, Protocol

from .config import Config

log = logging.getLogger(__name__)


class LLMError(Exception):
    pass


class LLM(Protocol):
    name: str

    def complete(self, system: str, user: str, max_tokens: int = 700) -> str: ...


class AnthropicLLM:
    def __init__(self, api_key: str, model: str):
        try:
            import anthropic
        except ImportError as exc:  # pragma: no cover
            raise LLMError("The 'anthropic' package is not installed") from exc
        self._client = anthropic.Anthropic(api_key=api_key)
        self.model = model
        self.name = model

    def complete(self, system: str, user: str, max_tokens: int = 700) -> str:
        try:
            resp = self._client.messages.create(
                model=self.model, max_tokens=max_tokens, system=system,
                messages=[{"role": "user", "content": user}])
        except Exception as exc:  # network, auth, rate limit...
            raise LLMError(str(exc)) from exc
        return "".join(block.text for block in resp.content if getattr(block, "type", "") == "text")


def build_llm(cfg: Config) -> Optional[LLM]:
    if not cfg.anthropic_api_key:
        log.warning("ANTHROPIC_API_KEY not set: using the offline fallback composer (labelled in the output).")
        return None
    try:
        return AnthropicLLM(cfg.anthropic_api_key, cfg.anthropic_model)
    except LLMError as exc:
        log.warning("LLM unavailable (%s): using offline fallback.", exc)
        return None


def parse_json(text: str) -> Any:
    """Parse a JSON object from model output, tolerating code fences and stray prose."""
    cleaned = re.sub(r"^```(?:json)?|```$", "", (text or "").strip(), flags=re.MULTILINE).strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        start, end = cleaned.find("{"), cleaned.rfind("}")
        if start != -1 and end > start:
            try:
                return json.loads(cleaned[start:end + 1])
            except json.JSONDecodeError:
                pass
    raise LLMError("Model did not return valid JSON")
