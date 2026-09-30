"""Manual Instagram DM queue. Never calls Instagram APIs or automates DMs."""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Any, Dict, List

from outreach.repositories import Repository

NOT_FOUND = "Not Found"


def enqueue_from_message(repo: Repository, message_id: int) -> Dict[str, Any]:
    message = repo.get_message(message_id)
    if message is None:
        return {"enqueued": False, "reason": "message not found"}
    influencer = repo.get_influencer(message["influencer_id"])
    if influencer is None:
        return {"enqueued": False, "reason": "influencer not found"}
    ig = influencer.get("instagram_url")
    if not ig or ig == NOT_FOUND:
        return {"enqueued": False, "reason": "no public Instagram URL"}
    queue_id = repo.enqueue_instagram_dm(
        influencer_id=influencer["id"],
        message_id=message_id,
        creator_name=influencer["name"],
        instagram_url=ig,
        dm_text=message.get("instagram_dm") or "",
    )
    return {"enqueued": True, "queue_id": queue_id}


def export_queue(repo: Repository, out_path: str | Path) -> Path:
    path = Path(out_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = repo.list_instagram_queue()
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(
            fh,
            fieldnames=[
                "queue_id",
                "influencer_id",
                "creator_name",
                "instagram_url",
                "dm_text",
                "status",
                "created_at",
                "manually_sent_at",
                "notes",
            ],
        )
        writer.writeheader()
        for row in rows:
            writer.writerow({k: row.get(k) for k in writer.fieldnames})
    return path


def mark_sent(repo: Repository, queue_id: int) -> bool:
    return repo.mark_instagram_sent(queue_id)


def list_queue(repo: Repository) -> List[Dict[str, Any]]:
    return repo.list_instagram_queue()
