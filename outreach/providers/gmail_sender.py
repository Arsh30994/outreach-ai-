"""Optional Gmail API sender. Never constructed in dry_run mode."""

from __future__ import annotations

import base64
import logging
from email.message import EmailMessage
from email.utils import make_msgid
from pathlib import Path

from outreach.config import Settings
from outreach.logging_config import redact
from outreach.providers.email_sender import SendResult

log = logging.getLogger(__name__)
GMAIL_SEND_SCOPE = ["https://www.googleapis.com/auth/gmail.send"]


class GmailSender:
    mode = "live"

    def __init__(self, settings: Settings, service=None):
        self.settings = settings
        self._service = service
        if service is None:
            self._service = self._build_service(settings)

    @staticmethod
    def _build_service(settings: Settings):
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow
        from googleapiclient.discovery import build

        creds_path = Path(settings.gmail_credentials_file)
        token_path = Path(settings.gmail_token_file)
        if not creds_path.is_file():
            raise RuntimeError("GMAIL_CREDENTIALS_FILE is missing")
        creds = None
        if token_path.is_file():
            creds = Credentials.from_authorized_user_file(str(token_path), GMAIL_SEND_SCOPE)
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                flow = InstalledAppFlow.from_client_secrets_file(str(creds_path), GMAIL_SEND_SCOPE)
                creds = flow.run_local_server(port=0)
            token_path.write_text(creds.to_json(), encoding="utf-8")
        return build("gmail", "v1", credentials=creds, cache_discovery=False)

    def _build_mime(self, to: str, subject: str, body: str) -> EmailMessage:
        msg = EmailMessage()
        msg["To"] = to
        msg["From"] = self.settings.brand.sender_email or "me"
        msg["Subject"] = subject
        msg["Message-ID"] = make_msgid()
        footer = [
            "",
            "--",
            "If you'd rather not hear from us, reply 'no thanks' and we won't contact you again.",
        ]
        if self.settings.brand.postal_address:
            footer.append(self.settings.brand.postal_address)
        msg.set_content(body + "\n" + "\n".join(footer))
        return msg

    def send(self, to: str, subject: str, body: str, idempotency_key: str) -> SendResult:
        mime = self._build_mime(to, subject, body)
        raw = base64.urlsafe_b64encode(mime.as_bytes()).decode("utf-8")
        try:
            sent = (
                self._service.users()
                .messages()
                .send(userId="me", body={"raw": raw})
                .execute()
            )
        except Exception as exc:
            log.error("Gmail send failed: %s", redact(str(exc)))
            return SendResult("FAILED", redact(str(exc)))
        return SendResult(
            status="SENT",
            detail=f"delivered to {to}",
            provider_message_id=str(sent.get("id") or mime["Message-ID"]),
        )
