"""Command line entry point.

Foundation commands: init-db, status, and quota.
Discovery, enrichment, generation, approval, and sending are not wired here yet.
"""

from __future__ import annotations

import argparse
import logging
import sys

from outreach.config import Settings, load_config
from outreach.db import database_status, init_db
from outreach.exceptions import ConfigError
from outreach.logging_config import configure_logging, redact

log = logging.getLogger("outreach.cli")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="outreach",
        description="CreatorReach AI foundation commands",
    )
    parser.add_argument("--config", default="config.yaml", help="Path to config.yaml")
    parser.add_argument("-v", "--verbose", action="store_true", help="Enable debug logging")
    commands = parser.add_subparsers(dest="cmd", required=True)
    commands.add_parser("init-db", help="Create the SQLite file and schema version table")
    commands.add_parser("status", help="Show whether the database has been initialized")
    commands.add_parser("quota", help="Show configured YouTube quota limits and recorded usage")
    return parser


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
    log.info("Loaded configuration: %s", settings.safe_summary())
    if args.cmd == "init-db":
        return _cmd_init_db(settings)
    if args.cmd == "status":
        return _cmd_status(settings)
    if args.cmd == "quota":
        return _cmd_quota(settings)
    print(f"Unknown command: {args.cmd}", file=sys.stderr)
    return 2


def _cmd_init_db(settings: Settings) -> int:
    version = init_db(settings.data.db_path)
    print(f"Database ready at {settings.data.db_path} (schema version {version})")
    return 0


def _cmd_status(settings: Settings) -> int:
    status = database_status(settings.data.db_path)
    print(f"Database: {status['path']}")
    print(f"Initialized: {'yes' if status['initialized'] else 'no'}")
    print(f"Schema version: {status['schema_version'] if status['schema_version'] is not None else 'none'}")
    print(f"Outreach mode: {settings.outreach_mode}")
    print(f"Follower range: {settings.discovery.min_followers}-{settings.discovery.max_followers}")
    print(f"Cache TTL days: {settings.cache.ttl_days}")
    print("Influencer records: unavailable until the persistence schema is applied")
    return 0


def _cmd_quota(settings: Settings) -> int:
    quota = settings.quota
    planned_calls = len(settings.discovery.queries) * settings.discovery.pages_per_query
    planned_units = planned_calls * quota.search_list
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
    print("  units used: 0")
    print("  search calls used: 0")
    print("Quota events are not recorded yet. Usage stays at 0 until the YouTube client is enabled.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
