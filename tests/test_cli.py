"""Foundation CLI commands."""

from __future__ import annotations

import os
import sqlite3
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path

import yaml

from outreach.cli import main
from tests.test_config import SECRET, base_config


class CliTests(unittest.TestCase):
    def setUp(self) -> None:
        self._saved = {
            key: os.environ.get(key)
            for key in (
                "YOUTUBE_API_KEY",
                "ANTHROPIC_API_KEY",
                "ANTHROPIC_MODEL",
                "OUTREACH_MODE",
                "SEND_TEST_EMAIL_TO",
                "GMAIL_CREDENTIALS_FILE",
                "GMAIL_TOKEN_FILE",
            )
        }
        for key in self._saved:
            os.environ.pop(key, None)

    def tearDown(self) -> None:
        for key, value in self._saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    def test_init_status_and_quota(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            db_path = Path(directory) / "outreach.db"
            payload = base_config()
            payload["data"]["db_path"] = str(db_path)
            config_path = Path(directory) / "config.yaml"
            config_path.write_text(yaml.safe_dump(payload), encoding="utf-8")

            status_before = StringIO()
            with redirect_stdout(status_before):
                code = main(["--config", str(config_path), "status"])
            self.assertEqual(code, 0)
            self.assertIn("Initialized: no", status_before.getvalue())

            init_out = StringIO()
            with redirect_stdout(init_out):
                self.assertEqual(main(["--config", str(config_path), "init-db"]), 0)
                self.assertEqual(main(["--config", str(config_path), "init-db"]), 0)
            self.assertIn("schema version 1", init_out.getvalue())

            connection = sqlite3.connect(db_path)
            try:
                rows = connection.execute("SELECT version, name FROM schema_migrations").fetchall()
            finally:
                connection.close()
            self.assertEqual(rows, [(1, "foundation")])

            status_after = StringIO()
            quota_out = StringIO()
            with redirect_stdout(status_after):
                self.assertEqual(main(["--config", str(config_path), "status"]), 0)
            with redirect_stdout(quota_out):
                self.assertEqual(main(["--config", str(config_path), "quota"]), 0)
            self.assertIn("Initialized: yes", status_after.getvalue())
            self.assertIn("Schema version: 1", status_after.getvalue())
            quota = quota_out.getvalue()
            self.assertIn("search.list units per page: 100", quota)
            self.assertIn("units used: 0", quota)
            self.assertIn("search calls used: 0", quota)

    def test_commands_do_not_print_api_keys(self) -> None:
        os.environ["YOUTUBE_API_KEY"] = SECRET
        os.environ["ANTHROPIC_API_KEY"] = "sk-ant-secretvalue123456"
        with tempfile.TemporaryDirectory() as directory:
            payload = base_config()
            payload["data"]["db_path"] = str(Path(directory) / "outreach.db")
            config_path = Path(directory) / "config.yaml"
            config_path.write_text(yaml.safe_dump(payload), encoding="utf-8")
            stdout = StringIO()
            stderr = StringIO()
            with redirect_stdout(stdout), redirect_stderr(stderr):
                code = main(["--config", str(config_path), "quota"])
            combined = stdout.getvalue() + stderr.getvalue()
            self.assertEqual(code, 0)
            self.assertNotIn(SECRET, combined)
            self.assertNotIn("sk-ant-secretvalue123456", combined)

    def test_missing_config_exits_nonzero(self) -> None:
        stderr = StringIO()
        with redirect_stderr(stderr):
            code = main(["--config", "does-not-exist.yaml", "status"])
        self.assertEqual(code, 2)
        self.assertIn("Config file not found", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
