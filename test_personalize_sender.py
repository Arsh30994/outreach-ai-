import json
import sqlite3
import unittest

from outreach import db
from outreach.config import Config
from outreach.personalize import (DM_WORDS, EMAIL_WORDS, build_facts, generate_messages, validate_dm,
                                  validate_email, word_count)
from outreach.sender import Outreach

PROFILE = {"name": "Code With Mia", "channel_id": "UC1", "niche": "Technology / AI",
           "content_themes": ["RAG", "python", "LLM apps"], "content_style": "Educational"}
VIDEOS = [{"title": "I Built a RAG Chatbot in 20 Minutes with Python"}]


class FakeLLM:
    name = "fake-model"

    def __init__(self, replies):
        self.replies, self.calls = list(replies), 0

    def complete(self, system, user, max_tokens=700):
        self.calls += 1
        return self.replies.pop(0) if self.replies else "garbage"


GOOD_EMAIL = json.dumps({"subject": "RAG chatbot idea", "body": (
    "Hi Mia, your video about building a RAG chatbot with Python was a clear, practical walkthrough. "
    "We build a code review tool for developers, and your LLM apps audience looks like a natural fit. "
    "We would like to offer a paid sponsored tutorial, with full creative control left to you. "
    "If that sounds interesting, reply and I will share details and rates.\n\nBest,\nAlex")})
GOOD_DM = json.dumps({"dm": "Hi Mia! Loved your RAG chatbot video with Python. YourBrand would love to explore a paid sponsored tutorial with you. Interested?"})


class PersonalizeTests(unittest.TestCase):
    def setUp(self):
        self.cfg = Config()

    def test_good_fixtures_are_in_range(self):
        self.assertTrue(EMAIL_WORDS[0] <= word_count(json.loads(GOOD_EMAIL)["body"]) <= EMAIL_WORDS[1])
        self.assertTrue(DM_WORDS[0] <= word_count(json.loads(GOOD_DM)["dm"]) <= DM_WORDS[1])

    def test_offline_fallback_always_within_limits_and_varied(self):
        bodies = set()
        for i in range(40):
            p = {**PROFILE, "channel_id": f"UC{i}", "name": f"Creator Number {i}"}
            v = [{"title": "An Extremely Long Video Title About Deep Learning With PyTorch " * (1 + i % 3)}]
            m = generate_messages(p, v, self.cfg, None)
            self.assertTrue(EMAIL_WORDS[0] <= word_count(m["email_body"]) <= EMAIL_WORDS[1], m["email_body"])
            self.assertTrue(DM_WORDS[0] <= word_count(m["instagram_dm"]) <= DM_WORDS[1], m["instagram_dm"])
            self.assertEqual(m["model"], "offline-fallback")
            bodies.add(m["email_body"].split(",")[0][:0] + m["email_body"][:40])
        self.assertGreater(len(bodies), 1)

    def test_llm_path_accepts_valid_output(self):
        llm = FakeLLM([GOOD_EMAIL, GOOD_DM])
        m = generate_messages(PROFILE, VIDEOS, self.cfg, llm)
        self.assertEqual(m["model"], "llm:fake-model")
        self.assertEqual(llm.calls, 2)

    def test_llm_retry_on_bad_word_count(self):
        bad = json.dumps({"subject": "x", "body": "Too short."})
        llm = FakeLLM([bad, GOOD_EMAIL, GOOD_DM])
        m = generate_messages(PROFILE, VIDEOS, self.cfg, llm)
        self.assertEqual(m["model"], "llm:fake-model")
        self.assertIn("attempt 1", m["notes"])

    def test_llm_failure_falls_back_and_is_labelled(self):
        llm = FakeLLM([])   # always returns garbage
        m = generate_messages(PROFILE, VIDEOS, self.cfg, llm)
        self.assertEqual(m["model"], "offline-fallback")
        self.assertIn("fell back", m["notes"])

    def test_validators_reject_placeholders_and_ungrounded(self):
        facts = build_facts(PROFILE, VIDEOS)
        body = "Hi [Name], " + "great content " * 25
        self.assertTrue(validate_email({"subject": "s", "body": body}, facts))
        self.assertTrue(validate_dm({"dm": "Hello there, we love your stuff and want to work together soon okay friend"}, facts))


class SenderTests(unittest.TestCase):
    def setUp(self):
        self.conn = db.connect(":memory:")
        self.cfg = Config(dry_run=True)
        self.inf = db.upsert_influencer(self.conn, {"channel_id": "UC1", "name": "Mia", "profile_url": "https://y/1",
                                                    "email": "mia@example.dev"})
        self.conn.execute("INSERT INTO messages (influencer_id, email_subject, email_body, instagram_dm, generated_at, approved)"
                          " VALUES (?,?,?,?,?,1)", (self.inf, "Subj", "Body text", "dm", db.now_iso()))
        self.conn.commit()

    def test_simulated_then_duplicate_blocked(self):
        s = Outreach(self.conn, self.cfg)
        self.assertEqual(s.send_email(self.inf).status, "SIMULATED")
        self.assertEqual(s.send_email(self.inf).status, "BLOCKED_DUPLICATE")
        statuses = [r["status"] for r in self.conn.execute("SELECT status FROM outreach ORDER BY id")]
        self.assertEqual(statuses, ["SIMULATED", "BLOCKED_DUPLICATE"])

    def test_unapproved_is_blocked(self):
        self.conn.execute("UPDATE messages SET approved = 0")
        self.assertEqual(Outreach(self.conn, self.cfg).send_email(self.inf).status, "BLOCKED_NOT_APPROVED")

    def test_missing_email_is_skipped(self):
        db.update_influencer(self.conn, self.inf, {"email": "Not Found"})
        self.assertEqual(Outreach(self.conn, self.cfg).send_email(self.inf).status, "SKIPPED_NO_EMAIL")

    def test_same_address_on_two_influencers_is_blocked(self):
        other = db.upsert_influencer(self.conn, {"channel_id": "UC2", "name": "Bo", "profile_url": "https://y/2",
                                                 "email": "MIA@example.dev"})
        self.conn.execute("INSERT INTO messages (influencer_id, email_subject, email_body, instagram_dm, generated_at, approved)"
                          " VALUES (?,?,?,?,?,1)", (other, "S", "B", "d", db.now_iso()))
        s = Outreach(self.conn, self.cfg)
        s.send_email(self.inf)
        self.assertEqual(s.send_email(other).status, "BLOCKED_DUPLICATE")

    def test_live_requires_confirm_and_redirects(self):
        class Capture:
            mode = "live"
            sent = []

            def send(self, msg):
                self.sent.append(msg)
                return "<id@x>"
        cap = Capture()
        cfg = Config(dry_run=False, test_recipient="me@mine.dev")
        s = Outreach(self.conn, cfg, transport=cap)
        self.assertEqual(s.send_email(self.inf).status, "BLOCKED_NOT_APPROVED")
        self.assertEqual(cap.sent, [])
        self.assertEqual(s.send_email(self.inf, confirm=True).status, "SENT")
        self.assertEqual(cap.sent[0]["To"], "me@mine.dev")
        row = self.conn.execute("SELECT intended_recipient, actual_recipient FROM outreach WHERE status='SENT'").fetchone()
        self.assertEqual((row[0], row[1]), ("mia@example.dev", "me@mine.dev"))
        self.assertEqual(s.send_email(self.inf, confirm=True).status, "BLOCKED_DUPLICATE")

    def test_transport_failure_is_logged_not_raised(self):
        class Broken:
            mode = "live"

            def send(self, msg):
                raise RuntimeError("smtp down")
        s = Outreach(self.conn, Config(dry_run=False), transport=Broken())
        res = s.send_email(self.inf, confirm=True)
        self.assertEqual(res.status, "FAILED")
        # a failed attempt can be retried
        s.transport = type("OK", (), {"mode": "live", "send": lambda self, m: "<ok>"})()
        self.assertEqual(s.send_email(self.inf, confirm=True).status, "SENT")

    def test_unique_index_is_a_hard_backstop(self):
        ins = "INSERT INTO outreach (influencer_id, channel, status, created_at) VALUES (?,?,?,?)"
        self.conn.execute(ins, (self.inf, "email", "SENT", db.now_iso()))
        with self.assertRaises(sqlite3.IntegrityError):
            self.conn.execute(ins, (self.inf, "email", "SENT", db.now_iso()))


if __name__ == "__main__":
    unittest.main()
