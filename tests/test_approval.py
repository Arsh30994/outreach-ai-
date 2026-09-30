"""Human approval gate — never sends email."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import yaml

from outreach.config import load_config
from outreach.db import connect, init_db
from outreach.exceptions import ApprovalError
from outreach.repositories import Repository
from outreach.services.approval import approve_message, reject_message
from outreach.services.offline_composer import offline_dm, offline_email
from outreach.services.personalization import build_facts
from tests.fixtures.youtube_fixtures import iso_days_ago
from tests.test_config import base_config


class ApprovalTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        path = str(Path(self.tmp.name) / "t.db")
        init_db(path)
        self.conn = connect(path)
        self.repo = Repository(self.conn)
        cfg_path = Path(self.tmp.name) / "c.yaml"
        cfg_path.write_text(yaml.safe_dump(base_config()), encoding="utf-8")
        self.settings = load_config(cfg_path)
        self.inf = self.repo.upsert_influencer(
            {
                "external_id": "UC1",
                "name": "Code With Mia",
                "profile_url": "https://www.youtube.com/channel/UC1",
                "followers": 20000,
                "followers_source": "api_reported",
                "niche": "Technology / AI",
                "content_themes": ["RAG", "python"],
                "contact_email": "mia@example.dev",
                "email_status": "found_public",
                "last_refreshed_at": iso_days_ago(1),
                "collected_at": iso_days_ago(1),
            }
        )
        self.repo.upsert_content_item(
            {
                "influencer_id": self.inf,
                "external_id": "v1",
                "title": "I Built a RAG Chatbot in 20 Minutes with Python",
                "url": "https://www.youtube.com/watch?v=v1",
            }
        )
        facts = build_facts(self.repo.get_influencer(self.inf), self.repo.list_content(self.inf))
        subject, body = offline_email(facts, self.settings.brand, "UC1")
        dm = offline_dm(facts, self.settings.brand, "UC1")
        self.message_id = self.repo.create_message(
            {
                "influencer_id": self.inf,
                "email_subject": subject,
                "email_body": body,
                "instagram_dm": dm,
                "status": "PENDING_REVIEW",
                "generation_method": "offline-fallback",
                "evidence_used": ["theme:RAG"],
            }
        )

    def tearDown(self) -> None:
        self.conn.close()
        self.tmp.cleanup()

    def test_pass_does_not_equal_approved(self) -> None:
        msg = self.repo.get_message(self.message_id)
        self.assertEqual(msg["status"], "PENDING_REVIEW")

    def test_approval_fails_without_email(self) -> None:
        self.repo.update_influencer(self.inf, {"contact_email": "Not Found"})
        with self.assertRaises(ApprovalError):
            approve_message(self.repo, self.message_id, "alex")

    def test_approval_fails_when_suppressed(self) -> None:
        self.repo.add_suppression("email", "mia@example.dev")
        with self.assertRaises(ApprovalError):
            approve_message(self.repo, self.message_id, "alex")

    def test_approval_fails_on_duplicate(self) -> None:
        self.repo.create_outreach_event(
            {
                "influencer_id": self.inf,
                "status": "SIMULATED",
                "idempotency_key": "prior",
                "intended_recipient": "mia@example.dev",
            }
        )
        with self.assertRaises(ApprovalError):
            approve_message(self.repo, self.message_id, "alex")

    def test_approval_succeeds(self) -> None:
        msg = approve_message(self.repo, self.message_id, "alex")
        self.assertEqual(msg["status"], "APPROVED")
        self.assertEqual(msg["reviewer"], "alex")
        self.assertIsNotNone(msg["approved_at"])

    def test_reject(self) -> None:
        reject_message(self.repo, self.message_id, "tone", "alex")
        self.assertEqual(self.repo.get_message(self.message_id)["status"], "REJECTED")


if __name__ == "__main__":
    unittest.main()
