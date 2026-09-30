"""Sending layer: validation, approval gate, duplicate prevention, dry-run/live transports, outreach log.

Safety defaults: DRY_RUN=true. In live mode every email goes to SEND_TEST_EMAIL_TO when it is set
(the log still records the intended recipient), and the operator must pass confirm=True.
"""
from __future__ import annotations

import logging
import smtplib
import sqlite3
from dataclasses import dataclass
from email.message import EmailMessage
from email.utils import make_msgid
from typing import Optional

from . import db
from .config import Config
from .enrichment import is_valid_email

log = logging.getLogger(__name__)

EMAIL = "email"


@dataclass
class SendResult:
    status: str           # SENT | SIMULATED | SKIPPED_NO_EMAIL | BLOCKED_NOT_APPROVED | BLOCKED_DUPLICATE | FAILED
    detail: str = ""


class DryRunTransport:
    mode = "dry-run"

    def send(self, msg: EmailMessage) -> str:
        return f"dry-run:{make_msgid(domain='dry-run.local')}"


class SMTPTransport:
    mode = "live"

    def __init__(self, cfg: Config):
        self.cfg = cfg

    def send(self, msg: EmailMessage) -> str:
        c = self.cfg
        if not (c.smtp_user and c.smtp_password):
            raise RuntimeError("SMTP_USER / SMTP_PASSWORD are not configured")
        with smtplib.SMTP(c.smtp_host, c.smtp_port, timeout=30) as server:
            server.starttls()
            server.login(c.smtp_user, c.smtp_password)
            server.send_message(msg)
        return msg["Message-ID"]


def footer(cfg: Config) -> str:
    lines = ["", "--", "If you'd rather not hear from us, reply 'no thanks' and we won't contact you again."]
    if cfg.brand.postal_address:
        lines.append(cfg.brand.postal_address)
    return "\n".join(lines)


def build_message(cfg: Config, subject: str, body: str, recipient: str) -> EmailMessage:
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = cfg.smtp_from or cfg.brand.sender_email or "outreach@localhost"
    msg["To"] = recipient
    if cfg.brand.sender_email:
        msg["Reply-To"] = cfg.brand.sender_email
    msg["Message-ID"] = make_msgid()
    msg.set_content(body + "\n" + footer(cfg))
    return msg


class Outreach:
    def __init__(self, conn: sqlite3.Connection, cfg: Config, transport=None):
        self.conn, self.cfg = conn, cfg
        self.transport = transport or (DryRunTransport() if cfg.dry_run else SMTPTransport(cfg))

    # ---- logging -----------------------------------------------------------
    def _log(self, inf_id: str, status: str, intended: Optional[str], actual: Optional[str],
             detail: str = "", provider_id: Optional[str] = None) -> None:
        self.conn.execute(
            """INSERT INTO outreach (influencer_id, channel, intended_recipient, actual_recipient, status,
                                     detail, provider_message_id, created_at) VALUES (?,?,?,?,?,?,?,?)""",
            (inf_id, EMAIL, intended, actual, status, detail, provider_id, db.now_iso()))
        self.conn.commit()

    def _already_done(self, inf_id: str, email: str, live: bool) -> Optional[str]:
        statuses = ("SENT",) if live else ("SENT", "SIMULATED")
        marks = ",".join("?" for _ in statuses)
        row = self.conn.execute(
            f"SELECT status FROM outreach WHERE channel = ? AND status IN ({marks}) "
            f"AND (influencer_id = ? OR lower(intended_recipient) = lower(?)) LIMIT 1",
            (EMAIL, *statuses, inf_id, email)).fetchone()
        return row["status"] if row else None

    # ---- main entry --------------------------------------------------------
    def send_email(self, inf_id: str, confirm: bool = False) -> SendResult:
        inf = db.get_influencer(self.conn, inf_id)
        if inf is None:
            return SendResult("FAILED", "unknown influencer")
        email = inf.get("email")
        if not is_valid_email(email):
            self._log(inf_id, "SKIPPED_NO_EMAIL", None, None, "no valid public email on record")
            return SendResult("SKIPPED_NO_EMAIL", "no valid public email on record")

        msg_row = self.conn.execute("SELECT * FROM messages WHERE influencer_id = ?", (inf_id,)).fetchone()
        if msg_row is None or not msg_row["approved"]:
            self._log(inf_id, "BLOCKED_NOT_APPROVED", email, None, "message missing or not approved")
            return SendResult("BLOCKED_NOT_APPROVED", "message missing or not approved")

        live = self.transport.mode == "live"
        prior = self._already_done(inf_id, email, live)
        if prior:
            self._log(inf_id, "BLOCKED_DUPLICATE", email, None, f"existing {prior} outreach found")
            return SendResult("BLOCKED_DUPLICATE", f"existing {prior} outreach found")

        if live and not confirm:
            return SendResult("BLOCKED_NOT_APPROVED", "live sending requires confirm=True (--confirm)")

        actual = (self.cfg.test_recipient or email) if live else email
        msg = build_message(self.cfg, msg_row["email_subject"], msg_row["email_body"], actual)
        try:
            provider_id = self.transport.send(msg)
        except Exception as exc:  # SMTP/network errors must not crash a batch
            log.error("send failed for %s: %s", inf_id, exc)
            self._log(inf_id, "FAILED", email, actual, str(exc))
            return SendResult("FAILED", str(exc))

        status = "SENT" if live else "SIMULATED"
        detail = f"delivered to {actual}" + (" (test redirect)" if live and actual != email else "") \
            if live else "dry-run: nothing was delivered"
        try:
            self._log(inf_id, status, email, actual, detail, provider_id)
        except sqlite3.IntegrityError:          # unique index: concurrent duplicate
            self._log(inf_id, "BLOCKED_DUPLICATE", email, None, "unique constraint prevented duplicate")
            return SendResult("BLOCKED_DUPLICATE", "unique constraint prevented duplicate")
        return SendResult(status, detail)
