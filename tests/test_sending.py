"""Dry-run / test / live sending and duplicate prevention."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import yaml

from outreach.config import load_config
from outreach.db import connect, init_db
from outreach.providers.dry_run_sender import DryRunSender
from outreach.repositories import Repository
from outreach.services.approval import approve_message
from outreach.services.offline_composer import offline_dm, offline_email
from outreach.services.outreach_service import OutreachService
from outreach.services.personalization import build_facts
from tests.fixtures.youtube_fixtures import iso_days_ago
from tests.test_config import base_config


class CaptureGmail:
    mode = "live"
    constructed = 0
    sent = []

    def __init__(self, settings):
        CaptureGmail.constructed += 1
        self.settings = settings

    def send(self, to, subject, body, idempotency_key):
        CaptureGmail.sent.append({"to": to, "subject": subject, "key": idempotency_key})
        return type("R", (), {"status": "SENT", "detail": f"delivered to {to}", "provider_message_id": "g1"})()


class SendingTests(unittest.TestCase):
    def setUp(self) -> None:
        CaptureGmail.constructed = 0
        CaptureGmail.sent = []
        self.tmp = tempfile.TemporaryDirectory()
        path = str(Path(self.tmp.name) / "t.db")
        init_db(path)
        self.conn = connect(path)
        self.repo = Repository(self.conn)
        cfg_path = Path(self.tmp.name) / "c.yaml"
        payload = base_config()
        cfg_path.write_text(yaml.safe_dump(payload), encoding="utf-8")
        self.settings = load_config(cfg_path)
        self.settings.send_test_email_to = "me@mine.dev"
        self.inf = self.repo.upsert_influencer(
            {
                "external_id": "UC1",
                "name": "Mia",
                "profile_url": "https://www.youtube.com/channel/UC1",
                "followers": 20000,
                "followers_source": "api_reported",
                "niche": "Technology / AI",
                "content_themes": ["python", "RAG"],
                "contact_email": "mia@example.dev",
                "last_refreshed_at": iso_days_ago(1),
                "collected_at": iso_days_ago(1),
            }
        )
        self.repo.upsert_content_item(
            {
                "influencer_id": self.inf,
                "external_id": "v1",
                "title": "Python RAG tutorial",
                "url": "https://www.youtube.com/watch?v=v1",
            }
        )
        facts = build_facts(self.repo.get_influencer(self.inf), self.repo.list_content(self.inf))
        subject, body = offline_email(facts, self.settings.brand, "UC1")
        self.message_id = self.repo.create_message(
            {
                "influencer_id": self.inf,
                "email_subject": subject,
                "email_body": body,
                "instagram_dm": offline_dm(facts, self.settings.brand, "UC1"),
                "status": "PENDING_REVIEW",
                "generation_method": "offline-fallback",
                "evidence_used": ["theme:python"],
            }
        )

    def tearDown(self) -> None:
        self.conn.close()
        self.tmp.cleanup()

    def test_unapproved_blocked(self) -> None:
        svc = OutreachService(self.repo, self.settings, sender=DryRunSender())
        res = svc.send_message(self.message_id, mode="dry_run")
        self.assertEqual(res.status, "BLOCKED_NOT_APPROVED")
        self.assertEqual(CaptureGmail.constructed, 0)

    def test_dry_run_never_constructs_gmail(self) -> None:
        approve_message(self.repo, self.message_id, "alex")
        svc = OutreachService(
            self.repo, self.settings, gmail_factory=CaptureGmail
        )
        res = svc.send_message(self.message_id, mode="dry_run")
        self.assertEqual(res.status, "SIMULATED")
        self.assertEqual(CaptureGmail.constructed, 0)
        self.assertEqual(CaptureGmail.sent, [])

    def test_duplicate_blocked(self) -> None:
        approve_message(self.repo, self.message_id, "alex")
        svc = OutreachService(self.repo, self.settings, sender=DryRunSender())
        self.assertEqual(svc.send_message(self.message_id, mode="dry_run").status, "SIMULATED")
        self.assertEqual(
            svc.send_message(self.message_id, mode="dry_run").status, "BLOCKED_DUPLICATE"
        )

    def test_test_mode_redirects(self) -> None:
        approve_message(self.repo, self.message_id, "alex")
        svc = OutreachService(self.repo, self.settings, gmail_factory=CaptureGmail)
        res = svc.send_message(self.message_id, mode="test", confirm=True)
        self.assertEqual(res.status, "SENT")
        self.assertEqual(CaptureGmail.sent[0]["to"], "me@mine.dev")
        row = self.repo.conn.execute(
            "SELECT intended_recipient, actual_recipient FROM outreach WHERE status='SENT'"
        ).fetchone()
        self.assertEqual(row[0], "mia@example.dev")
        self.assertEqual(row[1], "me@mine.dev")


if __name__ == "__main__":
    unittest.main()
