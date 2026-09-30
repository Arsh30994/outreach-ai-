"""Command line entry point for CreatorReach AI."""

from __future__ import annotations

import argparse
import logging
import sys
from typing import Optional

from outreach.config import Settings, load_config
from outreach.db import connect, init_db
from outreach.exceptions import ApprovalError, ConfigError, YouTubeAPIError
from outreach.export import export_all
from outreach.logging_config import configure_logging, redact
from outreach import pipeline
from outreach.providers.llm_provider import build_llm
from outreach.providers.youtube_client import YouTubeClient
from outreach.repositories import Repository
from outreach.services.approval import approve_message, format_review_item, list_pending, reject_message
from outreach.services.cache import ResponseCache
from outreach.services.instagram_queue import export_queue, list_queue, mark_sent
from outreach.services.outreach_service import OutreachService
from outreach.services.quota import QuotaManager
from outreach.services.website_fetcher import WebsiteFetcher
from outreach.status import print_status

log = logging.getLogger("outreach.cli")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="outreach",
        description="CreatorReach AI micro-influencer outreach CLI",
    )
    parser.add_argument("--config", default="config.yaml", help="Path to config.yaml")
    parser.add_argument("-v", "--verbose", action="store_true", help="Enable debug logging")
    commands = parser.add_subparsers(dest="cmd", required=True)

    commands.add_parser("init-db", help="Create/migrate the SQLite database")
    commands.add_parser("status", help="Show pipeline counters and DB status")
    commands.add_parser("quota", help="Show YouTube quota configuration and usage")
    commands.add_parser("discover", help="Search YouTube and store candidate channels")
    commands.add_parser("collect", help="Fetch recent videos and compute engagement")
    commands.add_parser("classify", help="Classify niche/themes (LLM or keyword fallback)")
    commands.add_parser("score", help="Apply hard gates and fit scoring")
    commands.add_parser("enrich", help="Public email/website/Instagram enrichment")
    gen = commands.add_parser("generate", help="Generate grounded email + DM drafts")
    gen.add_argument("--include-review", action="store_true", default=True)
    gen.add_argument("--pass-only", action="store_true")
    gen.add_argument("--force", action="store_true")
    commands.add_parser("review", help="List messages pending human review")
    ap = commands.add_parser("approve", help="Approve a message (does not send)")
    ap.add_argument("--message-id", type=int, required=True)
    ap.add_argument("--reviewer", required=True)
    rj = commands.add_parser("reject", help="Reject a pending message")
    rj.add_argument("--message-id", type=int, required=True)
    rj.add_argument("--reason", required=True)
    rj.add_argument("--reviewer", default="reviewer")
    sd = commands.add_parser("send", help="Send or simulate an approved message")
    sd.add_argument("--message-id", type=int, required=True)
    sd.add_argument("--mode", default="dry_run", choices=["dry_run", "test", "live"])
    sd.add_argument("--confirm", action="store_true")
    commands.add_parser("instagram-queue", help="Show/export Instagram manual DM queue")
    im = commands.add_parser("instagram-mark-sent", help="Mark a manual Instagram DM as sent")
    im.add_argument("--queue-id", type=int, required=True)
    commands.add_parser("export", help="Write CSV deliverables to data/")
    commands.add_parser("run", help="discover→collect→classify→score→enrich→generate→export")
    return parser


def _yt(settings: Settings, repo: Repository, run_id: Optional[int] = None) -> YouTubeClient:
    key = settings.require_youtube_api_key()
    cache = ResponseCache(repo, settings.cache.ttl_days)
    quota = QuotaManager(repo, settings.quota, discovery_run_id=run_id)
    return YouTubeClient(key, cache=cache, quota=quota)


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    configure_logging(verbose=args.verbose)
    try:
        settings = load_config(args.config)
    except ConfigError as exc:
        message = redact(f"Configuration error: {exc}")
        log.error("%s", message)
        print(message, file=sys.stderr)
        return 2

    if args.cmd == "init-db":
        version = init_db(settings.data.db_path)
        print(f"Database ready at {settings.data.db_path} (schema version {version})")
        return 0

    if args.cmd == "status":
        # Do not create the DB implicitly; status reports initialization honestly.
        from outreach.db import database_status

        status = database_status(settings.data.db_path)
        if not status["initialized"]:
            print(f"Database: {settings.data.db_path}")
            print("Initialized: no")
            print("Schema version: none")
            print(f"Outreach mode: {settings.outreach_mode}")
            print(
                f"Follower range: {settings.discovery.min_followers}-"
                f"{settings.discovery.max_followers}"
            )
            print(f"Cache TTL days: {settings.cache.ttl_days}")
            return 0
        conn = connect(settings.data.db_path)
        try:
            print_status(Repository(conn), settings)
        finally:
            conn.close()
        return 0

    # Ensure schema exists for operational commands.
    init_db(settings.data.db_path)
    conn = connect(settings.data.db_path)
    repo = Repository(conn)
    try:
        return _dispatch(args, settings, repo)
    except YouTubeAPIError as exc:
        print(f"YouTube error: {redact(str(exc))}", file=sys.stderr)
        return 1
    except ApprovalError as exc:
        print(f"Approval error: {exc}", file=sys.stderr)
        return 1
    finally:
        conn.close()


def _dispatch(args, settings: Settings, repo: Repository) -> int:
    if args.cmd == "quota":
        return _cmd_quota(settings, repo)
    if args.cmd == "discover":
        yt = _yt(settings, repo)
        print(pipeline.discover(repo, settings, yt))
        return 0
    if args.cmd == "collect":
        yt = _yt(settings, repo)
        print(pipeline.collect(repo, settings, yt))
        return 0
    if args.cmd == "classify":
        print(pipeline.classify_all(repo, settings, build_llm(settings)))
        return 0
    if args.cmd == "score":
        print(pipeline.score_all(repo, settings))
        return 0
    if args.cmd == "enrich":
        print(pipeline.enrich(repo, WebsiteFetcher()))
        return 0
    if args.cmd == "generate":
        include_review = not args.pass_only
        print(
            pipeline.generate_all(
                repo, settings, build_llm(settings), include_review=include_review, force=args.force
            )
        )
        return 0
    if args.cmd == "review":
        pending = list_pending(repo)
        if not pending:
            print("No messages pending review.")
            return 0
        for item in pending:
            print(format_review_item(item))
            print("-" * 40)
        return 0
    if args.cmd == "approve":
        msg = approve_message(repo, args.message_id, args.reviewer)
        print(f"APPROVED message_id={msg['id']} reviewer={msg['reviewer']}")
        return 0
    if args.cmd == "reject":
        reject_message(repo, args.message_id, args.reason, args.reviewer)
        print(f"REJECTED message_id={args.message_id}")
        return 0
    if args.cmd == "send":
        service = OutreachService(repo, settings)
        result = service.send_message(args.message_id, mode=args.mode, confirm=args.confirm)
        if args.mode == "dry_run":
            print("DRY RUN: nothing was sent to Gmail.")
        print(f"{result.status}: {result.detail}")
        return 0 if result.status in {"SIMULATED", "SENT"} else 1
    if args.cmd == "instagram-queue":
        path = export_queue(repo, f"{settings.data.export_dir}/instagram_dm_queue.csv")
        rows = list_queue(repo)
        print(f"queue_size={len(rows)} exported={path}")
        for row in rows:
            print(
                f"{row['queue_id']}: {row['creator_name']} {row['instagram_url']} [{row['status']}]"
            )
        return 0
    if args.cmd == "instagram-mark-sent":
        ok = mark_sent(repo, args.queue_id)
        print("updated" if ok else "not found")
        return 0 if ok else 1
    if args.cmd == "export":
        print(export_all(repo, settings.data.export_dir))
        return 0
    if args.cmd == "run":
        yt = _yt(settings, repo)
        summary = pipeline.run_pipeline(repo, settings, yt, build_llm(settings))
        _print_run_summary(repo, summary)
        return 0
    print(f"Unknown command: {args.cmd}", file=sys.stderr)
    return 2


def _cmd_quota(settings: Settings, repo: Repository) -> int:
    quota = settings.quota
    planned_calls = len(settings.discovery.queries) * settings.discovery.pages_per_query
    planned_units = planned_calls * quota.search_list
    usage = repo.calculate_quota_usage()
    print("YouTube quota configuration")
    print(f"  search.list units per page: {quota.search_list}")
    print(f"  channels.list units: {quota.channels_list}")
    print(f"  playlistItems.list units: {quota.playlist_items_list}")
    print(f"  videos.list units: {quota.videos_list}")
    print(f"  daily budget: {quota.daily_budget}")
    print(f"  safety budget: {quota.safety_budget}")
    print(f"  safety margin: {quota.safety_margin}")
    print(f"  search calls per day: {quota.search_calls_per_day}")
    print(f"  configured search pages: {planned_calls}")
    print(f"  configured search units: {planned_units}")
    print(f"  units used: {usage['units_used']}")
    print(f"  search calls used: {usage['search_calls_used']}")
    print(f"  cache hits: {usage['cache_hits']}")
    return 0


def _print_run_summary(repo: Repository, summary: dict) -> None:
    from outreach.status import collect_status
    # settings not needed beyond counts already in DB
    counts = {
        "discovered": repo.count_influencers(),
        "pass": repo.count_influencers("fit_status = 'PASS'"),
        "review": repo.count_influencers("fit_status = 'REVIEW'"),
        "fail": repo.count_influencers("fit_status = 'FAIL'"),
        "emails_found": repo.count_influencers(
            "contact_email IS NOT NULL AND contact_email != 'Not Found'"
        ),
        "messages_generated": repo.conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0],
        "pending_approval": repo.conn.execute(
            "SELECT COUNT(*) FROM messages WHERE status = 'PENDING_REVIEW'"
        ).fetchone()[0],
        "simulated": repo.conn.execute(
            "SELECT COUNT(*) FROM outreach WHERE status = 'SIMULATED'"
        ).fetchone()[0],
        "sent": repo.conn.execute(
            "SELECT COUNT(*) FROM outreach WHERE status = 'SENT'"
        ).fetchone()[0],
        "quota_used": repo.calculate_quota_usage()["units_used"],
    }
    print("RUN SUMMARY")
    for key, value in counts.items():
        print(f"  {key}: {value}")
    print(f"  stage_results: {summary}")


if __name__ == "__main__":
    sys.exit(main())
