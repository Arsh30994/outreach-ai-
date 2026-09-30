"""Logging setup that redacts API keys and tokens before they are written."""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import TextIO

_SECRET_SHAPES = (
    re.compile(r"AIza[0-9A-Za-z\-_]{20,}"),
    re.compile(r"sk-ant-[A-Za-z0-9\-_]{8,}"),
    re.compile(r"ya29\.[0-9A-Za-z\-._]+"),
    re.compile(r"(?i)\bbearer\s+[A-Za-z0-9\-._~+/]+=*"),
)
_SECRET_ASSIGNMENTS = re.compile(
    r"(?i)\b(api[_-]?key|access[_-]?token|refresh[_-]?token|token|password|secret|authorization)"
    r"(\s*[:=]\s*)(\S+)"
)
_SECRET_JSON = re.compile(
    r'(?i)("(?:api[_-]?key|access[_-]?token|refresh[_-]?token|token|password|secret)"\s*:\s*")[^"]+(")'
)


def redact(text: str) -> str:
    """Replace secret-shaped substrings. Non-secret text is returned unchanged."""
    if not text:
        return text
    redacted = text
    for pattern in _SECRET_SHAPES:
        redacted = pattern.sub("[REDACTED]", redacted)
    redacted = _SECRET_ASSIGNMENTS.sub(r"\1\2[REDACTED]", redacted)
    redacted = _SECRET_JSON.sub(r"\1[REDACTED]\2", redacted)
    return redacted


class RedactFormatter(logging.Formatter):
    """Format a log line, then strip secrets from the finished text."""

    def format(self, record: logging.LogRecord) -> str:
        return redact(super().format(record))


def configure_logging(
    verbose: bool = False,
    stream: TextIO | None = None,
    log_file: str | None = "logs/outreach.log",
) -> None:
    """Attach redacting handlers to the process logger.

    Existing outreach handlers are replaced so repeated CLI calls do not
    duplicate log lines. Handlers owned by the test runner are left in place.
    """
    root = logging.getLogger()
    root.setLevel(logging.DEBUG if verbose else logging.INFO)
    kept: list[logging.Handler] = []
    for handler in root.handlers:
        if getattr(handler, "_outreach", False):
            handler.close()
        else:
            kept.append(handler)
    root.handlers = kept

    formatter = RedactFormatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    stream_handler = logging.StreamHandler(stream)
    stream_handler.setFormatter(formatter)
    stream_handler._outreach = True  # type: ignore[attr-defined]
    root.addHandler(stream_handler)

    if log_file:
        path = Path(log_file)
        path.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(path, encoding="utf-8")
        file_handler.setFormatter(formatter)
        file_handler._outreach = True  # type: ignore[attr-defined]
        root.addHandler(file_handler)
