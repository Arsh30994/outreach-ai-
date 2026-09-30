"""Command line interface.  Run `python -m outreach.cli --help`."""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from . import db, pipeline
from .config import load_config
from .enrichment import PageFetcher
from .export import export_all
from .llm import build_llm
from .sender import Outreach
from .youtube import YouTubeAPIError, YouTubeClient


def _setup_logging(verbose: bool) -> None:
    Path("logs").mkdir(exist_ok=True)
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=[logging.StreamHandler(), logging.FileHandler("logs/outreach.log", encoding="utf-8")])


def _yt(cfg, conn) -> YouTubeClient:
    return YouTubeClient(cfg.youtube_api_key, cache=db.SQLiteCache(conn, cfg.cache_ttl_days),
                         quota_budget=cfg.quota_budget)


def cmd_status(conn, cfg) -> None:
    def count(sql: str, *params) -> int:
        return conn.execute(sql, params).fetchone()[0]

    print(f"Discovered:          {count('SELECT COUNT(*) FROM influencers')}")
    for s in ("PASS", "REVIEW", "FAIL", "DISCOVERED"):
        print(f"  {s:<18} {count('SELECT COUNT(*) FROM influencers WHERE status = ?', s)}")
    print(f"Emails found:        {count('SELECT COUNT(*) FROM influencers WHERE email != ?', 'Not Found')}")
    print(f"Messages generated:  {count('SELECT COUNT(*) FROM messages')}")
    print(f"Messages approved:   {count('SELECT COUNT(*) FROM messages WHERE approved = 1')}")
    for s in ("SENT", "SIMULATED", "BLOCKED_DUPLICATE", "BLOCKED_NOT_APPROVED", "FAILED", "SKIPPED_NO_EMAIL"):
        print(f"  {s:<20} {count('SELECT COUNT(*) FROM outreach WHERE status = ?', s)}")


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="outreach", description="Micro-influencer discovery & outreach pipeline")
    p.add_argument("--config", default="config.yaml")
    p.add_argument("-v", "--verbose", action="store_true")
    sub = p.add_subparsers(dest="cmd", required=True)
    for name, help_ in [("discover", "search YouTube and store candidate channels"),
                        ("collect", "fetch recent videos and compute engagement"),
                        ("classify", "classify niche/themes (LLM or keyword fallback)"),
                        ("score", "apply filtering rules and fit scoring"),
                        ("enrich", "find public emails/website/Instagram for shortlisted creators"),
                        ("generate", "generate email + DM for PASS creators"),
                        ("export", "write CSV deliverables"), ("status", "show pipeline counters")]:
        sp = sub.add_parser(name, help=help_)
        if name == "generate":
            sp.add_argument("--include-review", action="store_true")
            sp.add_argument("--force", action="store_true", help="regenerate existing messages")
    sp = sub.add_parser("run", help="discover -> collect -> classify -> score -> enrich -> generate -> export")
    sp = sub.add_parser("approve", help="approve generated messages (human review gate)")
    sp.add_argument("ids", nargs="*", help="influencer ids (e.g. yt_UC...)")
    sp.add_argument("--all-pass", action="store_true", help="approve every PASS creator with a message")
    sp = sub.add_parser("send", help="send (or simulate) approved emails")
    sp.add_argument("ids", nargs="*")
    sp.add_argument("--all-approved", action="store_true")
    sp.add_argument("--limit", type=int, default=5, help="max emails per invocation (safety)")
    sp.add_argument("--confirm", action="store_true", help="required for live sending when DRY_RUN=false")
    sp = sub.add_parser("dm-done", help="mark an Instagram DM as manually sent")
    sp.add_argument("ids", nargs="+")
    args = p.parse_args(argv)

    _setup_logging(args.verbose)
    cfg = load_config(args.config)
    conn = db.connect(cfg.db_path)
    llm = None

    try:
        if args.cmd in ("discover", "collect", "run"):
            yt = _yt(cfg, conn)
        if args.cmd in ("classify", "generate", "run"):
            llm = build_llm(cfg)

        def do_run() -> None:
            print("discover:", pipeline.discover(conn, cfg, yt))
            print("collect: ", pipeline.collect(conn, cfg, yt))
            print("classify:", pipeline.classify_all(conn, cfg, llm))
            print("score:   ", pipeline.score_all(conn, cfg))
            print("enrich:  ", pipeline.enrich_all(conn, cfg, PageFetcher()))
            print("generate:", pipeline.generate_all(conn, cfg, llm))
            print("export:  ", export_all(conn, cfg.export_dir))

        if args.cmd == "discover":
            print(pipeline.discover(conn, cfg, yt))
        elif args.cmd == "collect":
            print(pipeline.collect(conn, cfg, yt))
        elif args.cmd == "classify":
            print(pipeline.classify_all(conn, cfg, llm))
        elif args.cmd == "score":
            print(pipeline.score_all(conn, cfg))
        elif args.cmd == "enrich":
            print(pipeline.enrich_all(conn, cfg, PageFetcher()))
        elif args.cmd == "generate":
            print(pipeline.generate_all(conn, cfg, llm, args.include_review, args.force))
        elif args.cmd == "run":
            do_run()
        elif args.cmd == "export":
            print(export_all(conn, cfg.export_dir))
        elif args.cmd == "status":
            cmd_status(conn, cfg)
        elif args.cmd == "approve":
            ids = args.ids
            if args.all_pass:
                ids = [r["influencer_id"] for r in conn.execute(
                    "SELECT m.influencer_id FROM messages m JOIN influencers i ON i.id = m.influencer_id WHERE i.status = 'PASS'")]
            print("approved:", pipeline.approve(conn, ids))
        elif args.cmd == "send":
            ids = args.ids
            if args.all_approved:
                ids = [r["influencer_id"] for r in conn.execute("SELECT influencer_id FROM messages WHERE approved = 1")]
            sender = Outreach(conn, cfg)
            print(f"mode: {sender.transport.mode}" + (f" (redirect to {cfg.test_recipient})" if not cfg.dry_run and cfg.test_recipient else ""))
            for inf_id in ids[: args.limit]:
                res = sender.send_email(inf_id, confirm=args.confirm)
                print(f"{inf_id}: {res.status} - {res.detail}")
            if len(ids) > args.limit:
                print(f"{len(ids) - args.limit} skipped by --limit {args.limit}")
        elif args.cmd == "dm-done":
            for inf_id in args.ids:
                conn.execute("UPDATE messages SET dm_status = 'SENT_MANUALLY' WHERE influencer_id = ?", (inf_id,))
            conn.commit()
    except YouTubeAPIError as exc:
        print(f"YouTube error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
