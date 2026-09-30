# Automated Micro-Influencer Outreach System

Discovery → Data collection → Filtering → Enrichment → AI personalization → Human review → Sending → Tracking.
Built for the EDXSO AI Engineer Intern assignment (Technology / AI creators on YouTube).

**Data integrity rule:** nothing is fabricated. Every metric comes from the YouTube Data API or is calculated from
it; emails come only from public channel text / linked public pages; anything unavailable is written as
`Not Found`. Test fixtures are synthetic and live only inside `tests/`; they are never exported.

## Technology stack
Python 3.10+, `requests`, SQLite (`sqlite3`), PyYAML, python-dotenv, Anthropic SDK (optional), `unittest`.
SQL is kept portable so the DB can move to PostgreSQL.

## APIs / tools used
| Tool | Purpose |
|---|---|
| YouTube Data API v3 (`search`, `channels`, `playlistItems`, `videos`) | discovery, subscriber counts, recent video stats |
| Anthropic Claude API (optional) | niche/theme classification, email + DM generation |
| SMTP (e.g. Gmail app password) | live sending (off by default) |
| Public creator websites (robots.txt respected) | contact-email enrichment |

## Setup
```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env         # add YOUTUBE_API_KEY (and ANTHROPIC_API_KEY if you have one)
# edit config.yaml: brand block (placeholder brand!), queries, thresholds
python -m unittest discover -s tests -t .      # 40 tests, no network needed
python -m outreach.cli run                     # full pipeline, dry-run, writes CSVs to data/
```
Get a YouTube key: Google Cloud Console → enable *YouTube Data API v3* → Credentials → API key.

### Step-by-step commands
```bash
python -m outreach.cli discover      # search + store candidate channels
python -m outreach.cli collect       # recent videos + engagement for in-range channels
python -m outreach.cli classify      # niche/themes (LLM or keyword fallback)
python -m outreach.cli score         # PASS / REVIEW / FAIL with reasons
python -m outreach.cli enrich        # public email / website / Instagram for PASS+REVIEW
python -m outreach.cli generate      # email (60-90 words) + DM (15-30 words)
python -m outreach.cli export        # CSV deliverables
python -m outreach.cli approve --all-pass           # human-review gate (or approve specific ids)
python -m outreach.cli send --all-approved          # DRY-RUN by default -> status SIMULATED
python -m outreach.cli send --all-approved          # run again -> BLOCKED_DUPLICATE (demo of dedupe)
python -m outreach.cli status
```
Live sending: set `DRY_RUN=false`, SMTP vars, and `SEND_TEST_EMAIL_TO=you@yourmail` (all live mail is redirected
to you; the log keeps the intended recipient), then `send ... --confirm`. Max 5 emails per call (`--limit`).

## Data sources
YouTube Data API v3 (official). Instagram/TikTok are intentionally **not** scraped (ToS). Instagram handles are
only recorded when a creator links them publicly; DMs go to a manual queue.

## Discovery methodology
Keyword queries from `config.yaml` → `search.list` (type=channel) → de-duplicate → batched `channels.list`
(50 ids per call) → store all candidates → micro range 5,000–100,000 subscribers applied in filtering.
Quota: `search.list` = 100 units, other reads = 1 unit, default 10,000 units/day. The client tracks units, stops
at `quota_budget`, caches every response in SQLite (re-runs cost 0), retries 429/5xx with backoff, and fetches
recent videos through the uploads playlist (2 units) instead of searching. Subscriber counts are API-reported
and may be rounded by YouTube. Verify current quota costs in Google's docs before submitting.

## Filtering logic (`outreach/scoring.py`)
Hard gates → automatic **FAIL** with a reason: hidden/out-of-range subscribers, no public videos, no upload in
90 days, engagement < 1%. Otherwise a 100-point fit score:
audience size 20, niche relevance 25 (word-boundary term matches), content relevance 20 (share of recent videos
matching), engagement 20, activity 10, geography 5 (declared channel country vs `preferred_countries`).
≥75 PASS, 60–74 REVIEW, else FAIL. The per-component breakdown and reasons are stored and exported.
Having an email does not affect fit; it only decides whether email outreach is possible.

**Engagement rate** = (avg likes + avg comments) / avg views × 100 over the latest ≤10 public videos
(videos with hidden likes or zero views are excluded; sample size is stored). It is an approximation from public
data, not creator analytics.

## Enrichment process
For PASS/REVIEW creators only: regex the channel description for emails (filtering junk like `x@2x.png`), extract
website / Instagram links, then — if no email yet — fetch the creator's own site (`/`, `/contact`, `/about`) with
a polite fetcher (robots.txt, timeouts, size cap, public hosts only). Email source is recorded
(`channel_description` or `website:<url>`). YouTube's hidden "View email" button is **not** bypassed. Audience
age/gender/geography are not publicly available → `Not Found`. `Creator Country` is the creator-declared channel
country, not audience geography.

## AI model and prompts (`outreach/classify.py`, `outreach/personalize.py`)
Default model `claude-sonnet-5-5` (override with `ANTHROPIC_MODEL`). Three separate prompts: classification
(JSON), email (JSON subject/body), DM (JSON). Each is grounded only in supplied facts and forbids invention.

## Personalization logic
Inputs: channel name, niche, themes, style, most recent video title, brand block, collaboration type. Outputs are
validated in code (word counts, no `[placeholders]`, must reference real video/theme words). On failure the model
is re-prompted with the specific problem (3 attempts), then the **offline composer** is used, which builds the
text from the same real fields with seeded phrasing variation and is labelled `offline-fallback` in the output.
Compensation is stated explicitly (FTC: material connections must be disclosed).

## Sending mechanism (`outreach/sender.py`)
Requires valid public email + approved message. Dry-run by default (status `SIMULATED`). Duplicate prevention:
(1) check for prior SENT/SIMULATED by influencer **or** email address, (2) SQLite partial unique index as a hard
backstop. Append-only log in `outreach` table; statuses: SENT, SIMULATED, SKIPPED_NO_EMAIL,
BLOCKED_NOT_APPROVED, BLOCKED_DUPLICATE, FAILED. Emails get an opt-out line and postal address footer.
**Instagram DMs are never auto-sent**; they are written to `instagram_dm_queue.csv` for manual sending.

## Outputs (`data/`)
`influencers.csv` (all discovered, with PASS/REVIEW/FAIL + reasons, provenance columns), `personalized_messages.csv`,
`outreach_tracker.csv`, `outreach_log.csv`, `instagram_dm_queue.csv`, plus `outreach.db`.

## Scalability
Stages are idempotent and resumable (per-row timestamps), failures are isolated per creator (`last_error`),
responses are cached, quota is budgeted. For 500+ creators: more queries / `pages_per_query`, request a quota
increase, move SQLite → PostgreSQL, run stages as scheduled jobs.

## Limitations
- Emails: only a fraction of channels publish one; expect many `Not Found`.
- Engagement is approximate; subscriber counts may be rounded; niche matching is keyword-based.
- YouTube only; Instagram/TikTok are out of scope for automation.
- Brand block in `config.yaml` is a placeholder; edit before use.
- Tests use mocked APIs; run the live pipeline with your own keys. No audience demographics are available.
- Cold-email laws (CAN-SPAM/GDPR) and platform ToS apply to real campaigns; this prototype keeps a human in the loop.
