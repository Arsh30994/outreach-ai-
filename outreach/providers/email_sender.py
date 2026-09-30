"""Email sender interface and shared result type."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass
class SendResult:
    status: str
    detail: str = ""
    provider_message_id: str = ""


class EmailSender(Protocol):
    mode: str

    def send(self, to: str, subject: str, body: str, idempotency_key: str) -> SendResult: ...
