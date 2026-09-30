"""Public enrichment for PASS/REVIEW creators only."""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional
from urllib.parse import urljoin

from outreach.repositories import Repository
from outreach.services.email_extractor import NOT_FOUND, extract_emails, is_valid_email
from outreach.services.link_extractor import classify_urls, extract_urls
from outreach.services.website_fetcher import WebsiteFetcher
from outreach.time_utils import utc_now_iso

log = logging.getLogger(__name__)


def find_contact_email(
    description: str, website: str, fetcher: Optional[WebsiteFetcher], max_pages: int = 3
) -> tuple[str, str, str]:
    """Return (email, email_status, email_source_url)."""
    emails = extract_emails(description)
    if emails:
        return emails[0], "found_public", "channel_description"
    if fetcher and website != NOT_FOUND:
        pages = list(
            dict.fromkeys(
                [website, urljoin(website, "/contact"), urljoin(website, "/about")]
            )
        )
        for page in pages[:max_pages]:
            html = fetcher.fetch(page)
            if not html:
                continue
            emails = extract_emails(html)
            if emails:
                return emails[0], "found_public", page
    return NOT_FOUND, NOT_FOUND, NOT_FOUND


def enrich_profile(profile: Dict[str, Any], fetcher: Optional[WebsiteFetcher]) -> Dict[str, Any]:
    urls = extract_urls(profile.get("description") or "")
    website, instagram, tiktok = classify_urls(urls)
    email, status, source = find_contact_email(
        profile.get("description") or "", website, fetcher
    )
    return {
        "contact_email": email,
        "email_status": status,
        "email_source_url": source,
        "website": website,
        "instagram_url": instagram,
        "tiktok_url": tiktok,
        "audience_age": NOT_FOUND,
        "audience_gender": NOT_FOUND,
        "audience_geography": NOT_FOUND,
        "contactable": int(is_valid_email(email)),
    }


def enrich_all(repo: Repository, fetcher: Optional[WebsiteFetcher]) -> Dict[str, int]:
    found = missing = failed = 0
    rows = repo.list_influencers(
        "fit_status IN ('PASS','REVIEW') AND enriched_at IS NULL",
        order="fit_score DESC",
    )
    for row in rows:
        try:
            fields = enrich_profile(row, fetcher)
        except Exception as exc:  # isolate per creator
            log.error("enrichment failed for %s: %s", row.get("name"), exc)
            repo.record_error(row["id"], f"enrich: {exc}")
            failed += 1
            continue
        fields["enriched_at"] = utc_now_iso()
        repo.update_influencer(row["id"], fields)
        repo.add_field_provenance(
            row["id"], "contact_email", fields["contact_email"], fields["email_source_url"]
        )
        if fields["contact_email"] != NOT_FOUND:
            found += 1
        else:
            missing += 1
    return {"emails_found": found, "emails_not_found": missing, "failed": failed}
