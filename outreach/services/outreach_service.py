"""Send approved messages through DryRun / test / live senders."""

from __future__ import annotations

import hashlib
import logging
import sqlite3
from typing import Optional

from outreach.config import Settings
from outreach.providers.dry_run_sender import DryRunSender
from outreach.providers.email_sender import EmailSender, SendResult
from outreach.repositories import Repository, normalize_email
from outreach.services.email_extractor import is_valid_email

log = logging.getLogger(__name__)


def idempotency_key(influencer_id: str, email: str, message_id: int, mode: str) -> str:
    raw = f"{influencer_id}|{normalize_email(email)}|{message_id}|{mode}|email"
    return hashlib.sha256(raw.encode()).hexdigest()


def build_sender(settings: Settings, mode: str, gmail_factory=None) -> EmailSender:
    if mode == "dry_run":
        return DryRunSender()
    if mode in {"test", "live"}:
        if gmail_factory is not None:
            return gmail_factory(settings)
        from outreach.providers.gmail_sender import GmailSender

        return GmailSender(settings)
    raise ValueError(f"unsupported mode: {mode}")


class OutreachService:
    def __init__(
        self,
        repo: Repository,
        settings: Settings,
        sender: Optional[EmailSender] = None,
        gmail_factory=None,
    ):
        self.repo = repo
        self.settings = settings
        self.gmail_factory = gmail_factory
        self.sender = sender

    def send_message(
        self, message_id: int, mode: str = "dry_run", confirm: bool = False
    ) -> SendResult:
        mode = (mode or "dry_run").strip().lower()
        if mode not in {"dry_run", "test", "live"}:
            return SendResult("FAILED", f"invalid mode {mode}")
        if mode in {"test", "live"} and not confirm:
            return SendResult("BLOCKED_NOT_APPROVED", f"{mode} sending requires --confirm")

        message = self.repo.get_message(message_id)
        if message is None:
            return SendResult("FAILED", "unknown message")
        if message["status"] != "APPROVED":
            return SendResult("BLOCKED_NOT_APPROVED", "message is not approved")

        influencer = self.repo.get_influencer(message["influencer_id"])
        if influencer is None:
            return SendResult("FAILED", "unknown influencer")

        intended = influencer.get("contact_email")
        if not is_valid_email(intended):
            self._log(
                influencer["id"],
                message_id,
                "SKIPPED_NO_EMAIL",
                None,
                None,
                "no valid public email",
                mode,
                "skip-no-email",
            )
            return SendResult("SKIPPED_NO_EMAIL", "no valid public email")

        if self.repo.is_suppressed("email", intended) or self.repo.is_suppressed(
            "influencer", influencer["id"]
        ):
            return SendResult("BLOCKED_NOT_APPROVED", "suppressed")

        if self.repo.find_successful_outreach_by_influencer(influencer["id"]):
            return SendResult("BLOCKED_DUPLICATE", "prior successful outreach for creator")
        if self.repo.find_successful_outreach_by_email(intended):
            return SendResult("BLOCKED_DUPLICATE", "prior successful outreach for email")

        key = idempotency_key(influencer["id"], intended, message_id, mode)
        existing = self.repo.conn.execute(
            "SELECT status FROM outreach WHERE idempotency_key = ?", (key,)
        ).fetchone()
        if existing:
            return SendResult("BLOCKED_DUPLICATE", "idempotency key already used")

        if mode == "test":
            actual = self.settings.send_test_email_to
            if not actual:
                return SendResult("FAILED", "SEND_TEST_EMAIL_TO is required for test mode")
        elif mode == "live":
            actual = intended
        else:
            actual = intended

        sender = self.sender or build_sender(self.settings, mode, self.gmail_factory)
        # Safety: dry_run must never use GmailSender
        if mode == "dry_run" and sender.__class__.__name__ == "GmailSender":
            return SendResult("FAILED", "dry_run refused to use GmailSender")

        result = sender.send(
            actual, message["email_subject"], message["email_body"], key
        )
        status = result.status
        try:
            self._log(
                influencer["id"],
                message_id,
                status,
                intended,
                actual,
                result.detail,
                mode,
                key,
                result.provider_message_id,
            )
        except sqlite3.IntegrityError:
            return SendResult("BLOCKED_DUPLICATE", "unique constraint prevented duplicate")
        return result

    def _log(
        self,
        influencer_id: str,
        message_id: int,
        status: str,
        intended: Optional[str],
        actual: Optional[str],
        detail: str,
        mode: str,
        key: str,
        provider_id: Optional[str] = None,
    ) -> None:
        self.repo.create_outreach_event(
            {
                "influencer_id": influencer_id,
                "message_id": message_id,
                "status": status,
                "intended_recipient": intended,
                "actual_recipient": actual,
                "detail": detail,
                "idempotency_key": key,
                "mode": mode,
                "provider_message_id": provider_id,
            }
        )
