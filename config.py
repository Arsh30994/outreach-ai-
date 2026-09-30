"""Configuration loading: config.yaml for behaviour, environment variables for secrets."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import List

import yaml

try:  # optional
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover
    load_dotenv = None


@dataclass
class Brand:
    name: str = "YourBrand"
    product: str = "a product"
    value_prop: str = ""
    collaboration: str = "sponsored post"
    compensation: str = "paid compensation"
    sender_name: str = "The Team"
    sender_email: str = ""
    postal_address: str = ""


@dataclass
class Config:
    brand: Brand = field(default_factory=Brand)
    # discovery
    queries: List[str] = field(default_factory=list)
    max_results_per_query: int = 50
    pages_per_query: int = 1
    quota_budget: int = 9000
    min_followers: int = 5000
    max_followers: int = 100000
    recent_videos: int = 10
    cache_ttl_days: int = 7
    # filtering
    niche_label: str = "Technology / AI"
    niche_terms: List[str] = field(default_factory=list)
    preferred_countries: List[str] = field(default_factory=list)
    min_engagement: float = 1.0
    max_inactive_days: int = 90
    pass_score: int = 75
    review_score: int = 60
    # storage
    db_path: str = "data/outreach.db"
    export_dir: str = "data"
    # secrets / runtime (from environment)
    youtube_api_key: str = ""
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-sonnet-5-5"
    dry_run: bool = True
    test_recipient: str = ""
    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = ""


def _bool(value: str | None, default: bool) -> bool:
    if value is None or value == "":
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def load_config(path: str | Path = "config.yaml") -> Config:
    if load_dotenv:
        load_dotenv()
    raw = {}
    p = Path(path)
    if p.exists():
        raw = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    disc, filt, data = raw.get("discovery", {}), raw.get("filtering", {}), raw.get("data", {})
    cfg = Config(
        brand=Brand(**{**Brand().__dict__, **raw.get("brand", {})}),
        queries=list(disc.get("queries", [])),
        max_results_per_query=int(disc.get("max_results_per_query", 50)),
        pages_per_query=int(disc.get("pages_per_query", 1)),
        quota_budget=int(disc.get("quota_budget", 9000)),
        min_followers=int(disc.get("min_followers", 5000)),
        max_followers=int(disc.get("max_followers", 100000)),
        recent_videos=int(disc.get("recent_videos", 10)),
        cache_ttl_days=int(disc.get("cache_ttl_days", 7)),
        niche_label=filt.get("niche_label", "Technology / AI"),
        niche_terms=[t.lower() for t in filt.get("niche_terms", [])],
        preferred_countries=[c.upper() for c in filt.get("preferred_countries", [])],
        min_engagement=float(filt.get("min_engagement", 1.0)),
        max_inactive_days=int(filt.get("max_inactive_days", 90)),
        pass_score=int(filt.get("pass_score", 75)),
        review_score=int(filt.get("review_score", 60)),
        db_path=data.get("db_path", "data/outreach.db"),
        export_dir=data.get("export_dir", "data"),
        youtube_api_key=os.getenv("YOUTUBE_API_KEY", ""),
        anthropic_api_key=os.getenv("ANTHROPIC_API_KEY", ""),
        anthropic_model=os.getenv("ANTHROPIC_MODEL", "claude-sonnet-5-5"),
        dry_run=_bool(os.getenv("DRY_RUN"), True),
        test_recipient=os.getenv("SEND_TEST_EMAIL_TO", ""),
        smtp_host=os.getenv("SMTP_HOST", "smtp.gmail.com"),
        smtp_port=int(os.getenv("SMTP_PORT", "587") or 587),
        smtp_user=os.getenv("SMTP_USER", ""),
        smtp_password=os.getenv("SMTP_PASSWORD", ""),
        smtp_from=os.getenv("SMTP_FROM", ""),
    )
    return cfg
