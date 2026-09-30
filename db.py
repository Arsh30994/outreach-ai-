"""SQLite storage layer (swap the connection for Postgres later; SQL is kept portable)."""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

SCHEMA = """
CREATE TABLE IF NOT EXISTS influencers (
    id TEXT PRIMARY KEY,
    channel_id TEXT UNIQUE NOT NULL,
    name TEXT NOT NULL,
    platform TEXT NOT NULL DEFAULT 'YouTube',
    handle TEXT,
    profile_url TEXT NOT NULL,
    description TEXT,
    country TEXT,
    followers INTEGER,
    followers_hidden INTEGER DEFAULT 0,
    total_views INTEGER,
    video_count INTEGER,
    uploads_playlist TEXT,
    channel_keywords TEXT,
    engagement_rate REAL,
    engagement_method TEXT DEFAULT 'Not Found',
    engagement_sample_size INTEGER DEFAULT 0,
    last_upload_at TEXT,
    niche TEXT,
    content_themes TEXT DEFAULT '[]',
    content_style TEXT,
    audience_type TEXT,
    classification_source TEXT,
    email TEXT DEFAULT 'Not Found',
    email_source TEXT DEFAULT 'Not Found',
    website TEXT DEFAULT 'Not Found',
    instagram_url TEXT DEFAULT 'Not Found',
    audience_age TEXT DEFAULT 'Not Found',
    audience_gender TEXT DEFAULT 'Not Found',
    audience_geography TEXT DEFAULT 'Not Found',
    fit_score INTEGER,
    fit_breakdown TEXT,
    status TEXT DEFAULT 'DISCOVERED',
    status_reason TEXT,
    last_error TEXT,
    retrieved_at TEXT,
    collected_at TEXT,
    classified_at TEXT,
    scored_at TEXT,
    enriched_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS content_items (
    id TEXT PRIMARY KEY,
    influencer_id TEXT NOT NULL REFERENCES influencers(id),
    title TEXT NOT NULL,
    url TEXT NOT NULL,
    published_at TEXT,
    views INTEGER,
    likes INTEGER,
    comments INTEGER,
    description TEXT
);

CREATE TABLE IF NOT EXISTS messages (
    influencer_id TEXT PRIMARY KEY REFERENCES influencers(id),
    email_subject TEXT,
    email_body TEXT,
    instagram_dm TEXT,
    model TEXT,
    notes TEXT,
    generated_at TEXT NOT NULL,
    approved INTEGER DEFAULT 0,
    approved_at TEXT,
    dm_status TEXT DEFAULT 'MANUAL_REVIEW'
);

-- Append-only outreach log: one row per attempt.
CREATE TABLE IF NOT EXISTS outreach (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    influencer_id TEXT NOT NULL REFERENCES influencers(id),
    channel TEXT NOT NULL,
    intended_recipient TEXT,
    actual_recipient TEXT,
    status TEXT NOT NULL,
    detail TEXT,
    provider_message_id TEXT,
    created_at TEXT NOT NULL
);
-- Hard guarantee against duplicates: at most one SENT and one SIMULATED per influencer+channel.
CREATE UNIQUE INDEX IF NOT EXISTS ux_outreach_once
    ON outreach(influencer_id, channel, status) WHERE status IN ('SENT', 'SIMULATED');

CREATE TABLE IF NOT EXISTS api_cache (
    key TEXT PRIMARY KEY,
    payload TEXT NOT NULL,
    fetched_at TEXT NOT NULL
);
"""

JSON_FIELDS = {"content_themes", "fit_breakdown"}


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def connect(path: str = "data/outreach.db") -> sqlite3.Connection:
    if path != ":memory:":
        Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA)
    return conn


def _encode(fields: Dict[str, Any]) -> Dict[str, Any]:
    return {k: (json.dumps(v) if k in JSON_FIELDS and not isinstance(v, str) else v) for k, v in fields.items()}


def row_to_dict(row: sqlite3.Row | None) -> Optional[Dict[str, Any]]:
    if row is None:
        return None
    d = dict(row)
    for k in JSON_FIELDS:
        if k in d and isinstance(d[k], str):
            try:
                d[k] = json.loads(d[k])
            except json.JSONDecodeError:
                pass
    return d


def upsert_influencer(conn: sqlite3.Connection, data: Dict[str, Any]) -> str:
    """Insert a new influencer or refresh API-sourced fields of an existing one."""
    ts = now_iso()
    inf_id = data.get("id") or f"yt_{data['channel_id']}"
    data = _encode({**data, "id": inf_id})
    existing = conn.execute("SELECT id FROM influencers WHERE id = ?", (inf_id,)).fetchone()
    if existing:
        update_influencer(conn, inf_id, {k: v for k, v in data.items() if k != "id"})
    else:
        data.setdefault("created_at", ts)
        data["updated_at"] = ts
        cols = ", ".join(data)
        marks = ", ".join("?" for _ in data)
        conn.execute(f"INSERT INTO influencers ({cols}) VALUES ({marks})", list(data.values()))
        conn.commit()
    return inf_id


def update_influencer(conn: sqlite3.Connection, inf_id: str, fields: Dict[str, Any]) -> None:
    fields = _encode(dict(fields))
    fields["updated_at"] = now_iso()
    sets = ", ".join(f"{k} = ?" for k in fields)
    conn.execute(f"UPDATE influencers SET {sets} WHERE id = ?", [*fields.values(), inf_id])
    conn.commit()


def get_influencer(conn: sqlite3.Connection, inf_id: str) -> Optional[Dict[str, Any]]:
    return row_to_dict(conn.execute("SELECT * FROM influencers WHERE id = ?", (inf_id,)).fetchone())


def query_influencers(conn: sqlite3.Connection, where: str = "1=1", params: Iterable[Any] = (),
                      order: str = "fit_score DESC, followers DESC") -> List[Dict[str, Any]]:
    rows = conn.execute(f"SELECT * FROM influencers WHERE {where} ORDER BY {order}", list(params)).fetchall()
    return [row_to_dict(r) for r in rows]


def save_videos(conn: sqlite3.Connection, inf_id: str, videos: List[Dict[str, Any]]) -> None:
    for v in videos:
        conn.execute(
            """INSERT INTO content_items (id, influencer_id, title, url, published_at, views, likes, comments, description)
               VALUES (?,?,?,?,?,?,?,?,?)
               ON CONFLICT(id) DO UPDATE SET views=excluded.views, likes=excluded.likes,
                    comments=excluded.comments, title=excluded.title, description=excluded.description""",
            (v["id"], inf_id, v["title"], v["url"], v.get("published_at"), v.get("views"),
             v.get("likes"), v.get("comments"), v.get("description")),
        )
    conn.commit()


def get_videos(conn: sqlite3.Connection, inf_id: str) -> List[Dict[str, Any]]:
    rows = conn.execute(
        "SELECT * FROM content_items WHERE influencer_id = ? ORDER BY published_at DESC", (inf_id,)
    ).fetchall()
    return [dict(r) for r in rows]


class SQLiteCache:
    """Response cache so re-runs do not burn API quota."""

    def __init__(self, conn: sqlite3.Connection, ttl_days: int = 7):
        self.conn = conn
        self.ttl = timedelta(days=ttl_days)

    def get(self, key: str) -> Optional[dict]:
        row = self.conn.execute("SELECT payload, fetched_at FROM api_cache WHERE key = ?", (key,)).fetchone()
        if not row:
            return None
        fetched = datetime.fromisoformat(row["fetched_at"])
        if datetime.now(timezone.utc) - fetched > self.ttl:
            return None
        return json.loads(row["payload"])

    def set(self, key: str, payload: dict) -> None:
        self.conn.execute(
            "INSERT OR REPLACE INTO api_cache (key, payload, fetched_at) VALUES (?,?,?)",
            (key, json.dumps(payload), now_iso()),
        )
        self.conn.commit()
