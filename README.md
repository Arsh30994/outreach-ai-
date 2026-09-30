# CreatorReach AI

Python CLI for discovering technology and AI micro-influencers on YouTube and preparing outreach that a person approves before anything is sent.

This revision implements the project foundation:

- package layout for later pipeline stages
- `config.yaml` plus environment variables, validated with Pydantic
- secret redaction in logs and configuration errors
- SQLite bootstrap (`schema_migrations` only)
- commands `init-db`, `status`, and `quota`

YouTube requests, engagement math, scoring, enrichment, LLM calls, approval, Gmail, and Instagram export are not part of this revision. Older prototype modules remain at the repository root. The supported entry point is `python -m outreach.cli`.

## Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Run commands from the repository root.

## Environment variables

| Variable | Role |
|---|---|
| `YOUTUBE_API_KEY` | YouTube Data API key. Required only when a later discovery command asks for it. |
| `ANTHROPIC_API_KEY` | Optional Anthropic key. |
| `ANTHROPIC_MODEL` | Model name. Default `claude-sonnet-4-5`. |
| `OUTREACH_MODE` | `dry_run` (default), `test`, or `live`. |
| `SEND_TEST_EMAIL_TO` | Required when `OUTREACH_MODE=test`. |
| `GMAIL_CREDENTIALS_FILE` | OAuth client file. Required when `OUTREACH_MODE=live`. |
| `GMAIL_TOKEN_FILE` | OAuth token file. Required when `OUTREACH_MODE=live`. |

Optional overrides: `OUTREACH_DB_PATH`, `OUTREACH_EXPORT_DIR`, `MIN_FOLLOWERS`, `MAX_FOLLOWERS`, `PAGES_PER_QUERY`, `RECENT_UPLOAD_DAYS`, `MIN_ENGAGEMENT_RATE`, `QUOTA_DAILY_BUDGET`, `QUOTA_SAFETY_BUDGET`, `QUOTA_SAFETY_MARGIN`, `CACHE_TTL_DAYS`.

`test` mode fails config load until `SEND_TEST_EMAIL_TO` is set. `live` mode fails config load until both Gmail paths are set. `dry_run` loads without those values. API keys belong in `.env`, not in `config.yaml`.

## Configuration

`config.yaml` holds the brand placeholder, YouTube queries, follower range (5,000–100,000), minimum engagement (1.0), recent-upload window (90 days), preferred countries, collaboration type, quota costs, and cache TTL.

Shipped quota settings:

- `search.list`: 100 units per request/page
- `channels.list`: 1 unit
- `playlistItems.list`: 1 unit
- `videos.list`: 1 unit
- daily budget: 10,000 units
- safety budget: 9,000 units
- safety margin: 1,000 units
- search calls per day: 100
- one search page per query
- cache TTL: 7 days

The loader rejects a search plan whose pages would exceed the safety budget or the daily search-call cap. No YouTube calls are made by this revision, so recorded usage is 0.

## Commands

```bash
python -m outreach.cli init-db
python -m outreach.cli status
python -m outreach.cli quota
```

`init-db` creates `data/outreach.db` and the `schema_migrations` table (version 1, `foundation`). It is safe to run again. `status` reports that file and the configured follower range. `quota` prints the unit costs and the configured search plan.

## Tests

```bash
python -m unittest discover -s tests -t .
```

Tests cover configuration parsing, secret handling, and the three CLI commands. They do not call YouTube, Anthropic, or Gmail.

## Layout

```text
outreach/            package
outreach/services/   later pipeline stages
outreach/providers/  later API clients
outreach/prompts/    later prompt files
tests/               unit tests
tests/fixtures/      synthetic fixtures only
data/                local database (gitignored)
docs/                notes
config.yaml
.env.example
```

## Data handling in this revision

`init-db` writes a schema version and a UTC timestamp. It does not create influencer rows and does not insert sample creators. Audience demographics, emails, and engagement are not stored yet.
