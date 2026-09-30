"""Log redaction."""

from __future__ import annotations

import logging
import unittest
from io import StringIO

from outreach.logging_config import configure_logging, redact


class LoggingTests(unittest.TestCase):
    def test_redact_shapes_and_assignments(self) -> None:
        text = (
            "key=AIzaSySUPERSECRETKEY1234567890ABCDEF "
            "token=ya29.abcdef "
            "Authorization: Bearer abc.def "
            "api_key=sk-ant-secretvalue123456"
        )
        cleaned = redact(text)
        self.assertNotIn("AIzaSySUPERSECRETKEY1234567890ABCDEF", cleaned)
        self.assertNotIn("ya29.abcdef", cleaned)
        self.assertNotIn("Bearer abc.def", cleaned)
        self.assertNotIn("sk-ant-secretvalue123456", cleaned)
        self.assertIn("[REDACTED]", cleaned)

    def test_logger_redacts_records(self) -> None:
        stream = StringIO()
        configure_logging(stream=stream, log_file=None)
        logging.getLogger("outreach.test").info(
            "using api_key=%s",
            "AIzaSySUPERSECRETKEY1234567890ABCDEF",
        )
        output = stream.getvalue()
        self.assertNotIn("AIzaSySUPERSECRETKEY1234567890ABCDEF", output)
        self.assertIn("[REDACTED]", output)


if __name__ == "__main__":
    unittest.main()
