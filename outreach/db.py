"""SQLite bootstrap, migrations, and connection helpers."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from outreach.time_utils import utc_now_iso

SCHEMA_VERSION = 2
SCHEMA_NAME = "persistence"
SCHEMA_PATH = Path(__file__).with_name("schema.sql")


def connect(path: str) -> sqlite3.Connection:
    """Open SQLite with foreign keys enabled. Creates parent directories for file paths."""
    if path != ":memory:":
        Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(path: str) -> int:
    """Apply schema.sql and record the current schema version. Safe to re-run."""
    conn = connect(path)
    try:
        schema_sql = SCHEMA_PATH.read_text(encoding="utf-8")
        conn.executescript(schema_sql)
        existing = conn.execute(
            "SELECT version FROM schema_migrations WHERE version = ?",
            (SCHEMA_VERSION,),
        ).fetchone()
        if existing is None:
            # Keep historical foundation row if present; always ensure current version.
            conn.execute(
                "INSERT INTO schema_migrations (version, name, applied_at) VALUES (?, ?, ?)",
                (SCHEMA_VERSION, SCHEMA_NAME, utc_now_iso()),
            )
            # Ensure foundation marker exists for older DBs that only had v2 applied.
            foundation = conn.execute(
                "SELECT version FROM schema_migrations WHERE version = 1"
            ).fetchone()
            if foundation is None:
                conn.execute(
                    "INSERT INTO schema_migrations (version, name, applied_at) VALUES (?, ?, ?)",
                    (1, "foundation", utc_now_iso()),
                )
        conn.commit()
        current = conn.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0]
        return int(current)
    finally:
        conn.close()


def database_status(path: str) -> dict[str, object]:
    """Report whether the schema exists. Missing files are not an error."""
    if path != ":memory:" and not Path(path).is_file():
        return {"initialized": False, "path": path, "schema_version": None, "tables": []}
    conn = connect(path)
    try:
        table = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
            ("schema_migrations",),
        ).fetchone()
        if table is None:
            return {"initialized": False, "path": path, "schema_version": None, "tables": []}
        version = conn.execute("SELECT MAX(version) AS version FROM schema_migrations").fetchone()
        tables = [
            row["name"]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
            )
        ]
        return {
            "initialized": True,
            "path": path,
            "schema_version": None if version is None else version["version"],
            "tables": tables,
        }
    finally:
        conn.close()
