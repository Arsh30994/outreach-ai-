"""Message generation, validation, offline fallback."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import yaml

from outreach.config import load_config
from outreach.providers.llm_provider import FakeLLMProvider
from outreach.services.message_validation import DM_WORDS, EMAIL_WORDS, validate_dm, validate_email, word_count
from outreach.services.personalization import build_facts, generate_messages
from tests.test_config import base_config

PROFILE = {
    "name": "Code With Mia",
    "external_id": "UC1",
    "niche": "Technology / AI",
    "content_themes": ["RAG", "python", "LLM apps"],
    "content_style": "Educational",
}
VIDEOS = [{"title": "I Built a RAG Chatbot in 20 Minutes with Python"}]

GOOD_EMAIL = json.dumps(
    {
        "subject": "RAG chatbot idea",
        "body": (
            "Hi Mia, your video about building a RAG chatbot with Python was a clear, practical walkthrough. "
            "We build a code review tool for developers, and your LLM apps audience looks like a natural fit. "
            "We would like to offer a paid sponsored tutorial, with full creative control left to you. "
            "If that sounds interesting, reply and I will share details and rates.\n\nBest,\nAlex"
        ),
    }
)
GOOD_DM = json.dumps(
    {
        "dm": (
            "Hi Mia! Loved your RAG chatbot video with Python. "
            "YourBrand would love to explore a paid sponsored tutorial with you. Interested?"
        )
    }
)


def cfg():
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "c.yaml"
        path.write_text(yaml.safe_dump(base_config()), encoding="utf-8")
        return load_config(path)


class PersonalizeTests(unittest.TestCase):
    def test_offline_fallback_limits(self):
        bodies = set()
        settings = cfg()
        for i in range(20):
            p = {**PROFILE, "external_id": f"UC{i}", "name": f"Creator Number {i}"}
            v = [{"title": "Deep Learning With PyTorch Tutorial Episode " + str(i)}]
            m = generate_messages(p, v, settings, None)
            self.assertTrue(EMAIL_WORDS[0] <= word_count(m["email_body"]) <= EMAIL_WORDS[1], m["email_body"])
            self.assertTrue(DM_WORDS[0] <= word_count(m["instagram_dm"]) <= DM_WORDS[1], m["instagram_dm"])
            self.assertEqual(m["generation_method"], "offline-fallback")
            bodies.add(m["email_body"][:50])
        self.assertGreater(len(bodies), 1)

    def test_llm_accepts_valid(self):
        llm = FakeLLMProvider([GOOD_EMAIL, GOOD_DM])
        m = generate_messages(PROFILE, VIDEOS, cfg(), llm)
        self.assertEqual(m["model"], "llm:fake-model")
        self.assertEqual(llm.calls, 2)

    def test_llm_retry_then_success(self):
        bad = json.dumps({"subject": "x", "body": "Too short."})
        llm = FakeLLMProvider([bad, GOOD_EMAIL, GOOD_DM])
        m = generate_messages(PROFILE, VIDEOS, cfg(), llm)
        self.assertEqual(m["model"], "llm:fake-model")
        self.assertIn("attempt 1", m["notes"])

    def test_fallback_labelled(self):
        llm = FakeLLMProvider([])
        m = generate_messages(PROFILE, VIDEOS, cfg(), llm)
        self.assertEqual(m["generation_method"], "offline-fallback")

    def test_validators_reject_placeholders(self):
        facts = build_facts(PROFILE, VIDEOS)
        body = "Hi [Name], " + "great content " * 25
        self.assertTrue(validate_email({"subject": "s", "body": body}, facts))
        self.assertTrue(
            validate_dm(
                {"dm": "Hello there, we love your stuff and want to work together soon okay friend"},
                facts,
            )
        )


if __name__ == "__main__":
    unittest.main()
