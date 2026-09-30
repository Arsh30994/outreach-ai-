"""Parameterized SQLite repository methods for CreatorReach AI."""

from __future__ import annotations

import json
import sqlite3
from datetime import timedelta
from typing import Any, Iterable, Optional

from outreach.time_utils import utc_now, utc_now_iso

JSON_FIELDS = {
    "content_themes",
    "fit_components",
    "fit_reasons",
    "evidence_used",
    "queries_json",
}

NOT_FOUND = "Not Found"
SUCCESS_STATUSES = ("SENT", "SIMULATED")


def _encode(fields: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in fields.items():
        if key in JSON_FIELDS and value is not None and not isinstance(value, str):
            out[key] = json.dumps(value)
        else:
            out[key] = value
    return out


def _decode_row(row: sqlite3.Row | None) -> Optional[dict[str, Any]]:
    if row is None:
        return None
    data = dict(row)
    for key in JSON_FIELDS:
        if key in data and isinstance(data[key], str):
            try:
                data[key] = json.loads(data[key])
            except json.JSONDecodeError:
                pass
    return data


def normalize_email(value: Optional[str]) -> Optional[str]:
    if not value or value == NOT_FOUND:
        return None
    return value.strip().lower()


class Repository:
    """Thin data-access layer. Callers own the connection lifecycle for long jobs."""

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    # ---- discovery runs -------------------------------------------------
    def create_discovery_run(self, queries: list[str]) -> int:
        cur = self.conn.execute(
            """INSERT INTO discovery_runs (started_at, queries_json, status)
               VALUES (?, ?, 'running')""",
            (utc_now_iso(), json.dumps(queries)),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def finish_discovery_run(self, run_id: int, **fields: Any) -> None:
        fields = _encode(fields)
        fields["finished_at"] = utc_now_iso()
        fields.setdefault("status", "completed")
        sets = ", ".join(f"{k} = ?" for k in fields)
        self.conn.execute(
            f"UPDATE discovery_runs SET {sets} WHERE id = ?",
            [*fields.values(), run_id],
        )
        self.conn.commit()

    # ---- influencers ----------------------------------------------------
    def create_influencer(self, data: dict[str, Any]) -> str:
        ts = utc_now_iso()
        payload = _encode({**data})
        payload.setdefault("id", f"yt_{payload['external_id']}")
        payload.setdefault("platform", "YouTube")
        payload.setdefault("first_seen_at", ts)
        payload.setdefault("created_at", ts)
        payload["updated_at"] = ts
        cols = ", ".join(payload)
        marks = ", ".join("?" for _ in payload)
        self.conn.execute(
            f"INSERT INTO influencers ({cols}) VALUES ({marks})",
            list(payload.values()),
        )
        self.conn.commit()
        return str(payload["id"])

    def update_influencer(self, influencer_id: str, fields: dict[str, Any]) -> None:
        payload = _encode(dict(fields))
        payload["updated_at"] = utc_now_iso()
        sets = ", ".join(f"{k} = ?" for k in payload)
        self.conn.execute(
            f"UPDATE influencers SET {sets} WHERE id = ?",
            [*payload.values(), influencer_id],
        )
        self.conn.commit()

    def upsert_influencer(self, data: dict[str, Any]) -> str:
        platform = data.get("platform", "YouTube")
        external_id = data["external_id"]
        existing = self.get_influencer_by_external_id(platform, external_id)
        if existing:
            updates = {k: v for k, v in data.items() if k not in {"id", "created_at", "first_seen_at"}}
            updates["last_refreshed_at"] = utc_now_iso()
            self.update_influencer(existing["id"], updates)
            return existing["id"]
        return self.create_influencer(data)

    def get_influencer(self, influencer_id: str) -> Optional[dict[str, Any]]:
        row = self.conn.execute(
            "SELECT * FROM influencers WHERE id = ?", (influencer_id,)
        ).fetchone()
        return _decode_row(row)

    def get_influencer_by_external_id(
        self, platform: str, external_id: str
    ) -> Optional[dict[str, Any]]:
        row = self.conn.execute(
            "SELECT * FROM influencers WHERE platform = ? AND external_id = ?",
            (platform, external_id),
        ).fetchone()
        return _decode_row(row)

    def list_influencers(
        self,
        where: str = "1=1",
        params: Iterable[Any] = (),
        order: str = "fit_score DESC, followers DESC",
    ) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            f"SELECT * FROM influencers WHERE {where} ORDER BY {order}",
            list(params),
        ).fetchall()
        return [_decode_row(r) for r in rows]  # type: ignore[misc]

    def count_influencers(self, where: str = "1=1", params: Iterable[Any] = ()) -> int:
        return int(
            self.conn.execute(
                f"SELECT COUNT(*) FROM influencers WHERE {where}", list(params)
            ).fetchone()[0]
        )

    def record_error(self, influencer_id: str, error: str) -> None:
        self.update_influencer(
            influencer_id, {"last_error": error, "last_error_at": utc_now_iso()}
        )

    # ---- content --------------------------------------------------------
    def upsert_content_item(self, data: dict[str, Any]) -> str:
        ts = utc_now_iso()
        item_id = data.get("id") or data["external_id"]
        self.conn.execute(
            """INSERT INTO content_items
               (id, influencer_id, external_id, title, url, published_at, views, likes,
                comments, description, retrieved_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(influencer_id, external_id) DO UPDATE SET
                 title=excluded.title, url=excluded.url, published_at=excluded.published_at,
                 views=excluded.views, likes=excluded.likes, comments=excluded.comments,
                 description=excluded.description, retrieved_at=excluded.retrieved_at""",
            (
                item_id,
                data["influencer_id"],
                data["external_id"],
                data["title"],
                data["url"],
                data.get("published_at"),
                data.get("views"),
                data.get("likes"),
                data.get("comments"),
                data.get("description"),
                data.get("retrieved_at") or ts,
            ),
        )
        self.conn.commit()
        return item_id

    def list_content(self, influencer_id: str, limit: int = 10) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            """SELECT * FROM content_items WHERE influencer_id = ?
               ORDER BY published_at DESC LIMIT ?""",
            (influencer_id, limit),
        ).fetchall()
        return [dict(r) for r in rows]

    # ---- messages -------------------------------------------------------
    def create_message(self, data: dict[str, Any]) -> int:
        ts = utc_now_iso()
        payload = _encode(
            {
                **data,
                "status": data.get("status", "PENDING_REVIEW"),
                "generated_at": data.get("generated_at") or ts,
                "created_at": ts,
                "updated_at": ts,
            }
        )
        cols = ", ".join(payload)
        marks = ", ".join("?" for _ in payload)
        cur = self.conn.execute(
            f"INSERT INTO messages ({cols}) VALUES ({marks})", list(payload.values())
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def get_message(self, message_id: int) -> Optional[dict[str, Any]]:
        return _decode_row(
            self.conn.execute("SELECT * FROM messages WHERE id = ?", (message_id,)).fetchone()
        )

    def update_message_status(
        self,
        message_id: int,
        status: str,
        reviewer: Optional[str] = None,
        reason: Optional[str] = None,
    ) -> None:
        fields: dict[str, Any] = {"status": status, "updated_at": utc_now_iso()}
        if reviewer is not None:
            fields["reviewer"] = reviewer
        if reason is not None:
            fields["review_reason"] = reason
        if status == "APPROVED":
            fields["approved_at"] = utc_now_iso()
        elif status == "REJECTED":
            fields["rejected_at"] = utc_now_iso()
        elif status == "SUPERSEDED":
            fields["superseded_at"] = utc_now_iso()
        elif status == "EXPIRED":
            fields["expired_at"] = utc_now_iso()
        sets = ", ".join(f"{k} = ?" for k in fields)
        self.conn.execute(
            f"UPDATE messages SET {sets} WHERE id = ?", [*fields.values(), message_id]
        )
        self.conn.commit()

    def list_pending_messages(self) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            """SELECT m.*, i.name AS creator_name, i.profile_url, i.followers,
                      i.engagement_rate, i.engagement_sample_size, i.niche,
                      i.fit_score, i.fit_components, i.contact_email, i.email_source_url,
                      i.instagram_url, i.website
               FROM messages m
               JOIN influencers i ON i.id = m.influencer_id
               WHERE m.status = 'PENDING_REVIEW'
               ORDER BY m.generated_at DESC"""
        ).fetchall()
        return [_decode_row(r) for r in rows]  # type: ignore[misc]

    def get_latest_approved_message(self, influencer_id: str) -> Optional[dict[str, Any]]:
        return _decode_row(
            self.conn.execute(
                """SELECT * FROM messages WHERE influencer_id = ? AND status = 'APPROVED'
                   ORDER BY approved_at DESC LIMIT 1""",
                (influencer_id,),
            ).fetchone()
        )

    def supersede_pending_for_influencer(self, influencer_id: str) -> int:
        cur = self.conn.execute(
            """UPDATE messages SET status = 'SUPERSEDED', superseded_at = ?, updated_at = ?
               WHERE influencer_id = ? AND status = 'PENDING_REVIEW'""",
            (utc_now_iso(), utc_now_iso(), influencer_id),
        )
        self.conn.commit()
        return int(cur.rowcount)

    # ---- outreach -------------------------------------------------------
    def create_outreach_event(self, data: dict[str, Any]) -> int:
        payload = {
            "influencer_id": data["influencer_id"],
            "message_id": data.get("message_id"),
            "channel": data.get("channel", "email"),
            "intended_recipient": data.get("intended_recipient"),
            "actual_recipient": data.get("actual_recipient"),
            "normalized_email": normalize_email(
                data.get("normalized_email") or data.get("intended_recipient")
            ),
            "status": data["status"],
            "detail": data.get("detail"),
            "provider_message_id": data.get("provider_message_id"),
            "idempotency_key": data["idempotency_key"],
            "mode": data.get("mode", "dry_run"),
            "created_at": utc_now_iso(),
        }
        cols = ", ".join(payload)
        marks = ", ".join("?" for _ in payload)
        cur = self.conn.execute(
            f"INSERT INTO outreach ({cols}) VALUES ({marks})", list(payload.values())
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def find_successful_outreach_by_influencer(
        self, influencer_id: str, channel: str = "email"
    ) -> Optional[dict[str, Any]]:
        marks = ",".join("?" for _ in SUCCESS_STATUSES)
        return _decode_row(
            self.conn.execute(
                f"""SELECT * FROM outreach WHERE influencer_id = ? AND channel = ?
                    AND status IN ({marks}) ORDER BY id DESC LIMIT 1""",
                (influencer_id, channel, *SUCCESS_STATUSES),
            ).fetchone()
        )

    def find_successful_outreach_by_email(
        self, email: str, channel: str = "email"
    ) -> Optional[dict[str, Any]]:
        normalized = normalize_email(email)
        if not normalized:
            return None
        marks = ",".join("?" for _ in SUCCESS_STATUSES)
        return _decode_row(
            self.conn.execute(
                f"""SELECT * FROM outreach WHERE normalized_email = ? AND channel = ?
                    AND status IN ({marks}) ORDER BY id DESC LIMIT 1""",
                (normalized, channel, *SUCCESS_STATUSES),
            ).fetchone()
        )

    # ---- provenance -----------------------------------------------------
    def add_field_provenance(
        self,
        influencer_id: str,
        field_name: str,
        field_value: Any,
        source: str,
        retrieved_at: Optional[str] = None,
    ) -> None:
        value = field_value if isinstance(field_value, str) else json.dumps(field_value)
        self.conn.execute(
            """INSERT OR IGNORE INTO field_provenance
               (influencer_id, field_name, field_value, source, retrieved_at)
               VALUES (?,?,?,?,?)""",
            (influencer_id, field_name, value, source, retrieved_at or utc_now_iso()),
        )
        self.conn.commit()

    # ---- cache ----------------------------------------------------------
    def get_cached_response(self, cache_key: str) -> Optional[dict[str, Any]]:
        row = self.conn.execute(
            "SELECT payload, expires_at FROM api_cache WHERE cache_key = ?",
            (cache_key,),
        ).fetchone()
        if not row:
            return None
        if row["expires_at"] < utc_now_iso():
            return None
        return json.loads(row["payload"])

    def save_cached_response(
        self, cache_key: str, endpoint: str, payload: dict[str, Any], ttl_days: int
    ) -> None:
        fetched = utc_now()
        expires = (fetched + timedelta(days=ttl_days)).replace(microsecond=0).isoformat()
        self.conn.execute(
            """INSERT OR REPLACE INTO api_cache
               (cache_key, endpoint, payload, fetched_at, expires_at)
               VALUES (?,?,?,?,?)""",
            (cache_key, endpoint, json.dumps(payload), fetched.replace(microsecond=0).isoformat(), expires),
        )
        self.conn.commit()

    # ---- quota ----------------------------------------------------------
    def record_quota_event(
        self,
        endpoint: str,
        units: int,
        *,
        reserved: bool = True,
        search_call: bool = False,
        cache_hit: bool = False,
        discovery_run_id: Optional[int] = None,
        detail: Optional[str] = None,
    ) -> None:
        self.conn.execute(
            """INSERT INTO quota_events
               (endpoint, units, reserved, search_call, cache_hit, discovery_run_id, detail, created_at)
               VALUES (?,?,?,?,?,?,?,?)""",
            (
                endpoint,
                units,
                int(reserved),
                int(search_call),
                int(cache_hit),
                discovery_run_id,
                detail,
                utc_now_iso(),
            ),
        )
        self.conn.commit()

    def calculate_quota_usage(self) -> dict[str, int]:
        units = self.conn.execute(
            "SELECT COALESCE(SUM(units), 0) FROM quota_events WHERE cache_hit = 0 AND reserved = 1"
        ).fetchone()[0]
        search_calls = self.conn.execute(
            "SELECT COALESCE(SUM(search_call), 0) FROM quota_events WHERE cache_hit = 0"
        ).fetchone()[0]
        cache_hits = self.conn.execute(
            "SELECT COUNT(*) FROM quota_events WHERE cache_hit = 1"
        ).fetchone()[0]
        return {
            "units_used": int(units),
            "search_calls_used": int(search_calls),
            "cache_hits": int(cache_hits),
        }

    # ---- suppression ----------------------------------------------------
    def add_suppression(self, kind: str, value: str, reason: Optional[str] = None) -> None:
        self.conn.execute(
            """INSERT OR IGNORE INTO suppression_list (kind, value, reason, created_at)
               VALUES (?,?,?,?)""",
            (kind, value.strip().lower(), reason, utc_now_iso()),
        )
        self.conn.commit()

    def is_suppressed(self, kind: str, value: str) -> bool:
        row = self.conn.execute(
            "SELECT 1 FROM suppression_list WHERE kind = ? AND value = ?",
            (kind, value.strip().lower()),
        ).fetchone()
        return row is not None

    # ---- instagram queue ------------------------------------------------
    def enqueue_instagram_dm(
        self,
        influencer_id: str,
        message_id: int,
        creator_name: str,
        instagram_url: str,
        dm_text: str,
    ) -> int:
        cur = self.conn.execute(
            """INSERT OR IGNORE INTO instagram_dm_queue
               (influencer_id, message_id, creator_name, instagram_url, dm_text, status, created_at)
               VALUES (?,?,?,?,?,'PENDING_MANUAL_REVIEW',?)""",
            (influencer_id, message_id, creator_name, instagram_url, dm_text, utc_now_iso()),
        )
        self.conn.commit()
        if cur.lastrowid:
            return int(cur.lastrowid)
        row = self.conn.execute(
            "SELECT queue_id FROM instagram_dm_queue WHERE influencer_id = ? AND message_id = ?",
            (influencer_id, message_id),
        ).fetchone()
        return int(row["queue_id"])

    def list_instagram_queue(self) -> list[dict[str, Any]]:
        return [dict(r) for r in self.conn.execute(
            "SELECT * FROM instagram_dm_queue ORDER BY queue_id"
        )]

    def mark_instagram_sent(self, queue_id: int) -> bool:
        cur = self.conn.execute(
            """UPDATE instagram_dm_queue SET status = 'MANUALLY_SENT', manually_sent_at = ?
               WHERE queue_id = ?""",
            (utc_now_iso(), queue_id),
        )
        self.conn.commit()
        return cur.rowcount > 0
