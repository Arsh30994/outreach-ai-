"""Dry-run sender: never contacts Gmail or SMTP."""

from __future__ import annotations

from email.utils import make_msgid

from outreach.providers.email_sender import SendResult


class DryRunSender:
    mode = "dry_run"

    def send(self, to: str, subject: str, body: str, idempotency_key: str) -> SendResult:
        if not to or not subject or not body:
            return SendResult("FAILED", "missing to/subject/body")
        provider_id = make_msgid(domain="dry-run.local")
        return SendResult(
            status="SIMULATED",
            detail=f"dry-run: nothing was delivered (key={idempotency_key})",
            provider_message_id=provider_id,
        )
