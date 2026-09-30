"""SQLite bootstrap for the foundation CLI.

This module creates the schema-version table only. Influencer, content,
message, outreach, cache, quota, and suppression tables are added by a later
migration.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from outreach.time_utils import utc_now_iso

SCHEMA_VERSION = 1
SCHEMA_NAME = "foundation"


def connect(path: str) -> sqlite3.Connection:
    """Open SQLite with foreign keys enabled. Creates parent directories for file paths."""
    if path != ":memory:":
        Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(path: str) -> int:
    """Create the schema-version table. Repeated calls keep the current version."""
    conn = connect(path)
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                applied_at TEXT NOT NULL
            )
            """
        )
        existing = conn.execute(
            "SELECT version FROM schema_migrations WHERE version = ?",
            (SCHEMA_VERSION,),
        ).fetchone()
        if existing is None:
            conn.execute(
                "INSERT INTO schema_migrations (version, name, applied_at) VALUES (?, ?, ?)",
                (SCHEMA_VERSION, SCHEMA_NAME, utc_now_iso()),
            )
        conn.commit()
        current = conn.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0]
        return int(current)
    finally:
        conn.close()


def database_status(path: str) -> dict[str, object]:
    """Report whether the foundation schema exists. Missing files are not an error."""
    if path != ":memory:" and not Path(path).is_file():
        return {"initialized": False, "path": path, "schema_version": None}
    conn = connect(path)
    try:
        table = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
            ("schema_migrations",),
        ).fetchone()
        if table is None:
            return {"initialized": False, "path": path, "schema_version": None}
        version = conn.execute("SELECT MAX(version) AS version FROM schema_migrations").fetchone()
        return {
            "initialized": True,
            "path": path,
            "schema_version": None if version is None else version["version"],
        }
    finally:
        conn.close()
