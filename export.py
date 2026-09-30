"""CSV exports for the deliverables: dataset, messages, tracker and raw outreach log."""
from __future__ import annotations

import csv
from pathlib import Path
from typing import Dict, List

from . import db
from .personalize import word_count

FOLLOWERS_SOURCE = "YouTube Data API v3 channels.list (API-reported, may be rounded)"


def _write(path: Path, header: List[str], rows: List[List]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(header)
        writer.writerows(rows)
    return path


def _nf(value) -> str:
    return "Not Found" if value is None or value == "" else str(value)


def export_all(conn, out_dir: str) -> Dict[str, str]:
    out = Path(out_dir)
    infl = db.query_influencers(conn, order="CASE status WHEN 'PASS' THEN 0 WHEN 'REVIEW' THEN 1 ELSE 2 END, fit_score DESC, followers DESC")

    dataset = _write(out / "influencers.csv", [
        "Name", "Platform", "Followers", "Engagement (%)", "Niche", "Email", "Profile URL", "Content Theme", "Status",
        "Fit Score", "Status Reason", "Email Source", "Website", "Instagram", "Creator Country (declared)",
        "Audience Age", "Audience Gender", "Audience Geography", "Engagement Method", "Followers Source",
        "Classification Source", "Retrieved At"], [[
        i["name"], i["platform"], _nf(i["followers"]), _nf(i["engagement_rate"]), _nf(i["niche"]), i["email"],
        i["profile_url"], "; ".join(i["content_themes"]) if isinstance(i["content_themes"], list) else i["content_themes"],
        i["status"], _nf(i["fit_score"]), i["status_reason"] or "", i["email_source"], i["website"], i["instagram_url"],
        _nf(i["country"]), i["audience_age"], i["audience_gender"], i["audience_geography"],
        i["engagement_method"], FOLLOWERS_SOURCE, _nf(i["classification_source"]), _nf(i["retrieved_at"])]
        for i in infl])

    msgs = conn.execute("""SELECT i.name, i.email, i.profile_url, i.instagram_url, m.* FROM messages m
                           JOIN influencers i ON i.id = m.influencer_id ORDER BY i.fit_score DESC""").fetchall()
    messages = _write(out / "personalized_messages.csv", [
        "Influencer", "Email", "Profile URL", "Instagram", "Email Subject", "Email Body", "Email Words",
        "Instagram DM", "DM Words", "Model", "Approved", "DM Status", "Generation Notes"], [[
        m["name"], m["email"], m["profile_url"], m["instagram_url"], m["email_subject"], m["email_body"],
        word_count(m["email_body"]), m["instagram_dm"], word_count(m["instagram_dm"]), m["model"],
        "Yes" if m["approved"] else "No", m["dm_status"], m["notes"] or ""] for m in msgs])

    tracker_rows = []
    for m in msgs:
        inf_id = m["influencer_id"]
        logs = conn.execute("SELECT status, created_at FROM outreach WHERE influencer_id = ? AND channel = 'email' "
                            "ORDER BY id DESC", (inf_id,)).fetchall()
        sent = next((l for l in logs if l["status"] == "SENT"), None)
        sim = next((l for l in logs if l["status"] == "SIMULATED"), None)
        latest = logs[0] if logs else None
        tracker_rows.append([
            m["name"], m["email"], "Yes", "Yes" if sent else ("Simulated" if sim else "No"),
            (sent or sim or latest or {"created_at": ""})["created_at"],
            latest["status"] if latest else ("APPROVED_PENDING_SEND" if m["approved"] else "PENDING_APPROVAL")])
    tracker = _write(out / "outreach_tracker.csv",
                     ["Influencer", "Email", "Message Generated", "Sent", "Date", "Status"], tracker_rows)

    log_rows = conn.execute("""SELECT o.created_at, i.name, o.channel, o.intended_recipient, o.actual_recipient,
                                      o.status, o.detail, o.provider_message_id
                               FROM outreach o JOIN influencers i ON i.id = o.influencer_id ORDER BY o.id""").fetchall()
    log_csv = _write(out / "outreach_log.csv",
                     ["Timestamp", "Influencer", "Channel", "Intended Recipient", "Actual Recipient", "Status", "Detail",
                      "Provider Message ID"], [list(r) for r in log_rows])

    dm_rows = [[m["name"], m["profile_url"] if m["instagram_url"] == "Not Found" else m["instagram_url"],
                m["instagram_dm"], m["dm_status"]] for m in msgs]
    dm_queue = _write(out / "instagram_dm_queue.csv",
                      ["Influencer", "Profile to open", "DM (copy/paste manually)", "Status"], dm_rows)
    return {"dataset": str(dataset), "messages": str(messages), "tracker": str(tracker),
            "log": str(log_csv), "dm_queue": str(dm_queue)}
