"""CSV exports. Never includes synthetic test fixtures."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any, Dict, List

from outreach.repositories import Repository
from outreach.services.instagram_queue import export_queue
from outreach.services.message_validation import word_count

FOLLOWERS_SOURCE = "YouTube Data API v3 channels.list (API-reported, may be rounded)"


def _write(path: Path, header: List[str], rows: List[List[Any]]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(header)
        writer.writerows(rows)
    return path


def _nf(value: Any) -> str:
    return "Not Found" if value is None or value == "" else str(value)


def _json(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return json.dumps(value)


def export_all(repo: Repository, out_dir: str) -> Dict[str, str]:
    out = Path(out_dir)
    infl = repo.list_influencers(
        order=(
            "CASE fit_status WHEN 'PASS' THEN 0 WHEN 'REVIEW' THEN 1 ELSE 2 END, "
            "fit_score DESC, followers DESC"
        )
    )
    dataset = _write(
        out / "influencers.csv",
        [
            "id", "platform", "external_id", "Name", "Handle", "Profile URL",
            "Followers", "Followers Source", "Engagement (%)", "Engagement Method",
            "Engagement Sample Size", "Niche", "Content Themes", "Email", "Email Status",
            "Email Source", "Website", "Instagram", "Creator Country",
            "Audience Age", "Audience Gender", "Audience Geography",
            "Fit Score", "Fit Status", "Qualification Status", "Qualification Reason",
            "Contactable", "First Seen At", "Last Refreshed At",
        ],
        [
            [
                i["id"], i["platform"], i["external_id"], i["name"], _nf(i.get("handle")),
                i["profile_url"], _nf(i.get("followers")),
                i.get("followers_source") or FOLLOWERS_SOURCE,
                _nf(i.get("engagement_rate")), i.get("engagement_method"),
                i.get("engagement_sample_size"), _nf(i.get("niche")),
                _json(i.get("content_themes")), i.get("contact_email"),
                i.get("email_status"), i.get("email_source_url"), i.get("website"),
                i.get("instagram_url"), _nf(i.get("creator_country")),
                i.get("audience_age"), i.get("audience_gender"), i.get("audience_geography"),
                _nf(i.get("fit_score")), _nf(i.get("fit_status")),
                i.get("qualification_status"), i.get("qualification_reason") or "",
                i.get("contactable"), _nf(i.get("first_seen_at")), _nf(i.get("last_refreshed_at")),
            ]
            for i in infl
        ],
    )

    msgs = repo.conn.execute(
        """SELECT i.name, i.contact_email, i.profile_url, i.instagram_url, i.fit_score, m.*
           FROM messages m JOIN influencers i ON i.id = m.influencer_id
           ORDER BY i.fit_score DESC"""
    ).fetchall()
    messages = _write(
        out / "personalized_messages.csv",
        [
            "Message ID", "Influencer", "Email", "Profile URL", "Instagram",
            "Email Subject", "Email Body", "Email Words", "Instagram DM", "DM Words",
            "Status", "Model", "Generation Method", "Evidence", "Notes",
        ],
        [
            [
                m["id"], m["name"], m["contact_email"], m["profile_url"], m["instagram_url"],
                m["email_subject"], m["email_body"], word_count(m["email_body"] or ""),
                m["instagram_dm"], word_count(m["instagram_dm"] or ""), m["status"],
                m["model"], m["generation_method"], m["evidence_used"], m["notes"] or "",
            ]
            for m in msgs
        ],
    )

    tracker_rows = []
    for m in msgs:
        logs = repo.conn.execute(
            """SELECT status, created_at FROM outreach WHERE influencer_id = ?
               AND channel = 'email' ORDER BY id DESC""",
            (m["influencer_id"],),
        ).fetchall()
        sent = next((l for l in logs if l["status"] == "SENT"), None)
        sim = next((l for l in logs if l["status"] == "SIMULATED"), None)
        latest = logs[0] if logs else None
        tracker_rows.append(
            [
                m["name"],
                m["contact_email"],
                "Yes",
                "Yes" if sent else ("Simulated" if sim else "No"),
                (sent or sim or latest or {"created_at": ""})["created_at"],
                latest["status"]
                if latest
                else ("APPROVED_PENDING_SEND" if m["status"] == "APPROVED" else m["status"]),
            ]
        )
    tracker = _write(
        out / "outreach_tracker.csv",
        ["Influencer", "Email", "Message Generated", "Sent", "Date", "Status"],
        tracker_rows,
    )

    log_rows = repo.conn.execute(
        """SELECT o.created_at, i.name, o.channel, o.intended_recipient, o.actual_recipient,
                  o.status, o.detail, o.provider_message_id, o.idempotency_key, o.mode
           FROM outreach o JOIN influencers i ON i.id = o.influencer_id ORDER BY o.id"""
    ).fetchall()
    log_csv = _write(
        out / "outreach_log.csv",
        [
            "Timestamp", "Influencer", "Channel", "Intended Recipient", "Actual Recipient",
            "Status", "Detail", "Provider Message ID", "Idempotency Key", "Mode",
        ],
        [list(r) for r in log_rows],
    )
    dm_queue = export_queue(repo, out / "instagram_dm_queue.csv")
    return {
        "dataset": str(dataset),
        "messages": str(messages),
        "tracker": str(tracker),
        "log": str(log_csv),
        "dm_queue": str(dm_queue),
    }
