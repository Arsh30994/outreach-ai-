"""Human approval queue. Approval never sends email."""

from __future__ import annotations

from datetime import timedelta
from typing import Any, Dict, List, Optional

from outreach.exceptions import ApprovalError
from outreach.repositories import Repository
from outreach.services.email_extractor import is_valid_email
from outreach.services.message_validation import validate_dm, validate_email
from outreach.time_utils import utc_now, utc_now_iso


def _is_stale(profile: Dict[str, Any], max_age_days: int = 30) -> bool:
    stamp = profile.get("last_refreshed_at") or profile.get("collected_at") or profile.get("first_seen_at")
    if not stamp:
        return True
    try:
        from datetime import datetime
        dt = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    except ValueError:
        return True
    return utc_now() - dt > timedelta(days=max_age_days)


def list_pending(repo: Repository) -> List[Dict[str, Any]]:
    return repo.list_pending_messages()


def approve_message(
    repo: Repository,
    message_id: int,
    reviewer: str,
    stale_days: int = 30,
) -> Dict[str, Any]:
    if not reviewer or not reviewer.strip():
        raise ApprovalError("reviewer identity is required")
    message = repo.get_message(message_id)
    if message is None:
        raise ApprovalError(f"message {message_id} not found")
    if message["status"] != "PENDING_REVIEW":
        raise ApprovalError(f"message status is {message['status']}, expected PENDING_REVIEW")

    influencer = repo.get_influencer(message["influencer_id"])
    if influencer is None:
        raise ApprovalError("creator record missing")

    email = influencer.get("contact_email")
    if not is_valid_email(email):
        raise ApprovalError("valid public contact email is required")

    if repo.is_suppressed("email", email) or repo.is_suppressed("influencer", influencer["id"]):
        raise ApprovalError("creator or email is suppressed")

    if _is_stale(influencer, stale_days):
        raise ApprovalError("creator profile is stale; refresh before approval")

    if repo.find_successful_outreach_by_influencer(influencer["id"]):
        raise ApprovalError("prior successful outreach exists for creator")
    if repo.find_successful_outreach_by_email(email):
        raise ApprovalError("prior successful outreach exists for email")

    facts = {
        "name": influencer.get("name"),
        "niche": influencer.get("niche"),
        "themes": influencer.get("content_themes") or [],
        "video": "",
    }
    videos = repo.list_content(influencer["id"], limit=1)
    if videos:
        facts["video"] = videos[0].get("title") or ""

    email_problems = validate_email(
        {"subject": message.get("email_subject"), "body": message.get("email_body")}, facts
    )
    if email_problems:
        raise ApprovalError("invalid message: " + "; ".join(email_problems))
    dm_problems = validate_dm({"dm": message.get("instagram_dm")}, facts)
    if dm_problems:
        raise ApprovalError("invalid DM: " + "; ".join(dm_problems))

    repo.update_message_status(message_id, "APPROVED", reviewer=reviewer.strip())
    return repo.get_message(message_id)  # type: ignore[return-value]


def reject_message(repo: Repository, message_id: int, reason: str, reviewer: str = "reviewer") -> None:
    message = repo.get_message(message_id)
    if message is None:
        raise ApprovalError(f"message {message_id} not found")
    if message["status"] != "PENDING_REVIEW":
        raise ApprovalError(f"message status is {message['status']}")
    repo.update_message_status(
        message_id, "REJECTED", reviewer=reviewer, reason=reason or "rejected"
    )


def format_review_item(item: Dict[str, Any]) -> str:
    components = item.get("fit_components") or {}
    lines = [
        f"message_id={item['id']} status={item['status']}",
        f"creator={item.get('creator_name')} url={item.get('profile_url')}",
        f"followers={item.get('followers')} engagement={item.get('engagement_rate')} "
        f"sample={item.get('engagement_sample_size')}",
        f"niche={item.get('niche')} fit_score={item.get('fit_score')}",
        f"fit_components={components}",
        f"email={item.get('contact_email')} source={item.get('email_source_url')}",
        f"subject={item.get('email_subject')}",
        f"body={item.get('email_body')}",
        f"dm={item.get('instagram_dm')}",
        f"evidence={item.get('evidence_used')}",
    ]
    warnings = []
    if item.get("contact_email") in (None, "Not Found"):
        warnings.append("no public email")
    if warnings:
        lines.append("warnings=" + "; ".join(warnings))
    return "\n".join(lines)
