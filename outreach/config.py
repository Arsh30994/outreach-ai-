"""Load config.yaml and environment variables into a validated settings object.

Secrets are accepted only from the environment. They are stored as SecretStr
and omitted from string forms, summaries, and configuration errors.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, ConfigDict, Field, SecretStr, ValidationError, field_validator, model_validator

from outreach.exceptions import ConfigError

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_COUNTRY_RE = re.compile(r"^[A-Z]{2}$")
_FORBIDDEN_KEY_NAMES = {
    "youtube_api_key",
    "anthropic_api_key",
    "api_key",
    "apikey",
    "smtp_password",
    "password",
    "token",
    "secret",
    "gmail_token",
    "credentials",
    "client_secret",
}


class BrandSettings(BaseModel):
    """Placeholder brand used later for grounded outreach copy."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    product: str = Field(min_length=1)
    value_prop: str = Field(min_length=1)
    collaboration: str = Field(min_length=1)
    compensation: str = Field(min_length=1)
    sender_name: str = Field(min_length=1)
    sender_email: str = Field(min_length=1)
    postal_address: str = Field(min_length=1)


class DiscoverySettings(BaseModel):
    """YouTube discovery inputs. Search calls are not made by this layer."""

    model_config = ConfigDict(extra="forbid")

    queries: list[str] = Field(min_length=1)
    max_results_per_query: int = Field(default=50, ge=1, le=50)
    pages_per_query: int = Field(default=1, ge=1)
    min_followers: int = Field(default=5000, ge=0)
    max_followers: int = Field(default=100000, ge=1)
    recent_videos: int = Field(default=10, ge=1, le=50)

    @field_validator("queries")
    @classmethod
    def _clean_queries(cls, values: list[str]) -> list[str]:
        cleaned = [item.strip() for item in values if item and item.strip()]
        if not cleaned:
            raise ValueError("at least one discovery query is required")
        return cleaned

    @model_validator(mode="after")
    def _follower_range(self) -> DiscoverySettings:
        if self.min_followers > self.max_followers:
            raise ValueError("min_followers cannot exceed max_followers")
        return self


class FilteringSettings(BaseModel):
    """Thresholds for later hard gates and fit scoring."""

    model_config = ConfigDict(extra="forbid")

    niche_label: str = Field(min_length=1)
    niche_terms: list[str] = Field(min_length=1)
    preferred_countries: list[str] = Field(default_factory=list)
    minimum_engagement_rate: float = Field(ge=0)
    recent_upload_days: int = Field(ge=1)
    pass_score: int = Field(default=75, ge=0, le=100)
    review_score: int = Field(default=60, ge=0, le=100)

    @field_validator("niche_terms")
    @classmethod
    def _clean_terms(cls, values: list[str]) -> list[str]:
        cleaned = [item.strip().lower() for item in values if item and item.strip()]
        if not cleaned:
            raise ValueError("at least one niche term is required")
        return cleaned

    @field_validator("preferred_countries")
    @classmethod
    def _clean_countries(cls, values: list[str]) -> list[str]:
        cleaned = [item.strip().upper() for item in values if item and item.strip()]
        invalid = [item for item in cleaned if not _COUNTRY_RE.fullmatch(item)]
        if invalid:
            raise ValueError("preferred_countries must be ISO 3166-1 alpha-2 codes")
        return cleaned

    @model_validator(mode="after")
    def _score_order(self) -> FilteringSettings:
        if self.review_score > self.pass_score:
            raise ValueError("review_score cannot exceed pass_score")
        return self


class QuotaSettings(BaseModel):
    """YouTube Data API unit costs and local safety limits."""

    model_config = ConfigDict(extra="forbid")

    search_list: int = Field(default=100, ge=1)
    channels_list: int = Field(default=1, ge=1)
    playlist_items_list: int = Field(default=1, ge=1)
    videos_list: int = Field(default=1, ge=1)
    daily_budget: int = Field(default=10000, ge=1)
    safety_budget: int = Field(default=9000, ge=1)
    safety_margin: int = Field(default=1000, ge=0)
    search_calls_per_day: int = Field(default=100, ge=1)

    @model_validator(mode="after")
    def _budget_consistency(self) -> QuotaSettings:
        if self.safety_budget > self.daily_budget:
            raise ValueError("safety_budget cannot exceed daily_budget")
        expected_margin = self.daily_budget - self.safety_budget
        if self.safety_margin != expected_margin:
            raise ValueError("safety_margin must equal daily_budget minus safety_budget")
        return self


class CacheSettings(BaseModel):
    """Response-cache lifetime. Cache storage arrives with the YouTube client."""

    model_config = ConfigDict(extra="forbid")

    ttl_days: int = Field(default=7, ge=0)


class DataSettings(BaseModel):
    """Local paths. The database file is created by the init-db command."""

    model_config = ConfigDict(extra="forbid")

    db_path: str = "data/outreach.db"
    export_dir: str = "data"


class Settings(BaseModel):
    """Validated runtime configuration."""

    model_config = ConfigDict(extra="forbid")

    brand: BrandSettings
    discovery: DiscoverySettings
    filtering: FilteringSettings
    quota: QuotaSettings
    cache: CacheSettings
    data: DataSettings
    youtube_api_key: SecretStr = SecretStr("")
    anthropic_api_key: SecretStr = SecretStr("")
    anthropic_model: str = "claude-sonnet-4-5"
    outreach_mode: str = "dry_run"
    send_test_email_to: str = ""
    gmail_credentials_file: str = ""
    gmail_token_file: str = ""

    @field_validator("outreach_mode")
    @classmethod
    def _mode(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in {"dry_run", "test", "live"}:
            raise ValueError("outreach_mode must be dry_run, test, or live")
        return normalized

    @field_validator("send_test_email_to")
    @classmethod
    def _test_recipient(cls, value: str) -> str:
        cleaned = value.strip()
        if cleaned and not _EMAIL_RE.fullmatch(cleaned):
            raise ValueError("SEND_TEST_EMAIL_TO must be an email address")
        return cleaned

    @model_validator(mode="after")
    def _mode_requirements(self) -> Settings:
        if self.outreach_mode == "test" and not self.send_test_email_to:
            raise ValueError("SEND_TEST_EMAIL_TO is required when OUTREACH_MODE is test")
        if self.outreach_mode == "live":
            if not self.gmail_credentials_file.strip():
                raise ValueError("GMAIL_CREDENTIALS_FILE is required when OUTREACH_MODE is live")
            if not self.gmail_token_file.strip():
                raise ValueError("GMAIL_TOKEN_FILE is required when OUTREACH_MODE is live")
        planned_calls = len(self.discovery.queries) * self.discovery.pages_per_query
        planned_units = planned_calls * self.quota.search_list
        if planned_units > self.quota.safety_budget:
            raise ValueError(
                "configured search plan exceeds the quota safety budget; "
                "reduce queries or pages_per_query"
            )
        if planned_calls > self.quota.search_calls_per_day:
            raise ValueError(
                "configured search plan exceeds search_calls_per_day; "
                "reduce queries or pages_per_query"
            )
        return self

    def require_youtube_api_key(self) -> str:
        """Return the YouTube key or raise without echoing any stored value."""
        value = self.youtube_api_key.get_secret_value().strip()
        if not value:
            raise ConfigError(
                "YOUTUBE_API_KEY is not set. Add it to the environment or a .env file."
            )
        return value

    def safe_summary(self) -> str:
        """Describe the loaded settings without secret values."""
        youtube = "set" if self.youtube_api_key.get_secret_value().strip() else "missing"
        anthropic = "set" if self.anthropic_api_key.get_secret_value().strip() else "missing"
        return (
            f"mode={self.outreach_mode} db={self.data.db_path} "
            f"queries={len(self.discovery.queries)} "
            f"followers={self.discovery.min_followers}-{self.discovery.max_followers} "
            f"youtube_api_key={youtube} anthropic_api_key={anthropic} "
            f"model={self.anthropic_model}"
        )

    def __str__(self) -> str:
        return self.safe_summary()

    def __repr__(self) -> str:
        return f"Settings({self.safe_summary()})"


def load_config(path: str | Path = "config.yaml") -> Settings:
    """Load, overlay environment overrides, and validate settings."""
    load_dotenv(override=False)
    config_path = Path(path)
    raw = _read_yaml(config_path)
    _reject_embedded_secrets(raw)
    try:
        return Settings.model_validate(_merge_env(_normalize(raw)))
    except ValidationError as exc:
        raise ConfigError(_safe_validation_message(exc)) from exc
    except ConfigError:
        raise
    except ValueError as exc:
        raise ConfigError(str(exc)) from exc


def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise ConfigError(f"Config file not found: {path}")
    try:
        loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ConfigError(f"Could not parse config file {path}: {exc.__class__.__name__}") from exc
    if loaded is None:
        raise ConfigError(f"Config file is empty: {path}")
    if not isinstance(loaded, dict):
        raise ConfigError(f"Config file must be a mapping: {path}")
    return loaded


def _reject_embedded_secrets(node: Any, found: list[str] | None = None) -> None:
    names = found if found is not None else []
    if isinstance(node, dict):
        for key, value in node.items():
            if str(key).lower() in _FORBIDDEN_KEY_NAMES:
                names.append(str(key))
            else:
                _reject_embedded_secrets(value, names)
    elif isinstance(node, list):
        for item in node:
            _reject_embedded_secrets(item, names)
    if found is None and names:
        listed = ", ".join(sorted(set(names)))
        raise ConfigError(
            f"config.yaml must not contain secrets ({listed}). Set them in the environment."
        )


def _normalize(raw: dict[str, Any]) -> dict[str, Any]:
    brand = dict(raw.get("brand") or {})
    discovery = dict(raw.get("discovery") or {})
    filtering = dict(raw.get("filtering") or {})
    quota = dict(raw.get("quota") or {})
    cache = dict(raw.get("cache") or {})
    data = dict(raw.get("data") or {})

    if "minimum_engagement_rate" not in filtering and "min_engagement" in filtering:
        filtering["minimum_engagement_rate"] = filtering["min_engagement"]
    if "recent_upload_days" not in filtering and "max_inactive_days" in filtering:
        filtering["recent_upload_days"] = filtering["max_inactive_days"]
    filtering.pop("min_engagement", None)
    filtering.pop("max_inactive_days", None)

    if "ttl_days" not in cache and "cache_ttl_days" in discovery:
        cache["ttl_days"] = discovery["cache_ttl_days"]
    if "safety_budget" not in quota and "quota_budget" in discovery:
        quota["safety_budget"] = discovery["quota_budget"]
    for legacy_key in ("quota_budget", "cache_ttl_days"):
        discovery.pop(legacy_key, None)

    quota.setdefault("search_list", 100)
    quota.setdefault("channels_list", 1)
    quota.setdefault("playlist_items_list", 1)
    quota.setdefault("videos_list", 1)
    quota.setdefault("daily_budget", 10000)
    quota.setdefault("safety_budget", 9000)
    quota.setdefault("search_calls_per_day", 100)
    quota.setdefault("safety_margin", int(quota["daily_budget"]) - int(quota["safety_budget"]))
    cache.setdefault("ttl_days", 7)

    return {
        "brand": brand,
        "discovery": discovery,
        "filtering": filtering,
        "quota": quota,
        "cache": cache,
        "data": data,
    }


def _merge_env(data: dict[str, Any]) -> dict[str, Any]:
    """Apply environment overrides. Blank variables do not replace YAML values."""
    _set_int(data, "MIN_FOLLOWERS", "discovery", "min_followers")
    _set_int(data, "MAX_FOLLOWERS", "discovery", "max_followers")
    _set_int(data, "PAGES_PER_QUERY", "discovery", "pages_per_query")
    _set_int(data, "RECENT_UPLOAD_DAYS", "filtering", "recent_upload_days")
    _set_float(data, "MIN_ENGAGEMENT_RATE", "filtering", "minimum_engagement_rate")
    budget_set = _set_int(data, "QUOTA_SAFETY_BUDGET", "quota", "safety_budget")
    daily_set = _set_int(data, "QUOTA_DAILY_BUDGET", "quota", "daily_budget")
    margin_set = _set_int(data, "QUOTA_SAFETY_MARGIN", "quota", "safety_margin")
    _set_int(data, "CACHE_TTL_DAYS", "cache", "ttl_days")

    if (budget_set or daily_set) and not margin_set:
        data["quota"]["safety_margin"] = int(data["quota"]["daily_budget"]) - int(
            data["quota"]["safety_budget"]
        )

    db_path = os.getenv("OUTREACH_DB_PATH", "").strip()
    if db_path:
        data["data"]["db_path"] = db_path
    export_dir = os.getenv("OUTREACH_EXPORT_DIR", "").strip()
    if export_dir:
        data["data"]["export_dir"] = export_dir

    data["youtube_api_key"] = os.getenv("YOUTUBE_API_KEY", "")
    data["anthropic_api_key"] = os.getenv("ANTHROPIC_API_KEY", "")
    model = os.getenv("ANTHROPIC_MODEL", "").strip()
    if model:
        data["anthropic_model"] = model
    mode = os.getenv("OUTREACH_MODE", "").strip()
    if mode:
        data["outreach_mode"] = mode
    data["send_test_email_to"] = os.getenv("SEND_TEST_EMAIL_TO", "")
    data["gmail_credentials_file"] = os.getenv("GMAIL_CREDENTIALS_FILE", "")
    data["gmail_token_file"] = os.getenv("GMAIL_TOKEN_FILE", "")
    return data


def _set_int(data: dict[str, Any], env_name: str, section: str, field: str) -> bool:
    raw = os.getenv(env_name)
    if raw is None or raw.strip() == "":
        return False
    try:
        data[section][field] = int(raw.strip())
    except ValueError as exc:
        raise ConfigError(f"{env_name} must be an integer.") from exc
    return True


def _set_float(data: dict[str, Any], env_name: str, section: str, field: str) -> bool:
    raw = os.getenv(env_name)
    if raw is None or raw.strip() == "":
        return False
    try:
        data[section][field] = float(raw.strip())
    except ValueError as exc:
        raise ConfigError(f"{env_name} must be a number.") from exc
    return True


def _safe_validation_message(exc: ValidationError) -> str:
    """Build a validation message from locations and messages, never from input values."""
    parts: list[str] = []
    for error in exc.errors():
        location = ".".join(str(item) for item in error.get("loc", ())) or "config"
        message = str(error.get("msg", "invalid value"))
        parts.append(f"{location}: {message}")
    if not parts:
        return "Configuration is invalid."
    return "Configuration is invalid: " + "; ".join(parts)
