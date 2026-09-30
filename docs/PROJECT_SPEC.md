# CreatorReach AI — Project Specification

You are the lead engineer for this repository.

Build an AI-powered micro-influencer outreach MVP for the EDXSO AI Engineer Intern assignment.

## Product

CreatorReach AI discovers technology and AI micro-influencers on YouTube,
normalizes public creator data, calculates transparent public engagement
estimates, filters creators, enriches public contact information, generates
grounded outreach messages, routes messages through human approval, and
supports dry-run email sending with duplicate prevention.

## Primary platform

YouTube only.

## Initial niche

Technology, artificial intelligence, programming, developer tools.

## Micro-influencer range

5,000–100,000 subscribers, configurable.

## Core workflow

Discovery → normalization → recent-content collection → engagement
calculation → niche classification → fit scoring → public enrichment →
message generation → validation → human approval → dry-run/test sending →
outreach tracking.

## Non-negotiable data-integrity rules

1. Never fabricate influencer records.
2. Never guess or generate email addresses.
3. Use "Not Found" for unavailable enrichment fields.
4. Never infer audience age, gender, or geography from content.
5. Label subscriber counts as API-reported.
6. Label engagement as independently calculated public engagement.
7. Store field provenance and retrieval timestamps.
8. Do not scrape Instagram or TikTok.
9. Record Instagram handles only when publicly linked by the creator.
10. Never automatically send Instagram DMs.
11. Never send Gmail messages without explicit human approval.
12. Dry-run mode is the default.
13. Never allow duplicate successful outreach.
14. Never expose API keys or OAuth tokens in logs.

## Technology

- Python 3.11+
- Standard library sqlite3 for persistence
- requests
- PyYAML
- python-dotenv
- Pydantic
- google-api-python-client
- google-auth-oauthlib
- Anthropic SDK as an optional dependency
- unittest or pytest
- CLI-first architecture
- Optional lightweight dashboard only after the backend works

## Repository structure

- outreach/
- outreach/services/
- outreach/providers/
- outreach/prompts/
- tests/
- data/
- docs/
- config.yaml
- requirements.txt
- .env.example
- README.md

## Required commands

```bash
python -m outreach.cli init-db
python -m outreach.cli discover
python -m outreach.cli collect
python -m outreach.cli classify
python -m outreach.cli score
python -m outreach.cli enrich
python -m outreach.cli generate
python -m outreach.cli review
python -m outreach.cli approve --message-id MESSAGE_ID
python -m outreach.cli send --message-id MESSAGE_ID --mode dry_run
python -m outreach.cli export
python -m outreach.cli status
python -m outreach.cli quota
python -m unittest discover -s tests -t .
```

## YouTube quota

- search.list: configure as 100 quota units per request/page.
- channels.list: 1 unit.
- playlistItems.list: 1 unit.
- videos.list: 1 unit.
- Cache all successful responses.
- Track quota events in SQLite.
- Track search calls separately.
- Reserve quota before uncached requests.
- Stop at a safety budget.
- Retry only transient 429 and 5xx errors.
- Do not retry quotaExceeded, invalid credentials, invalid requests,
  forbidden, or not-found errors.
- Pagination must be explicit and quota-aware.

## Discovery

- Read queries from config.yaml.
- Use search.list with type=channel.
- Deduplicate by channel ID.
- Batch channels.list requests with up to 50 IDs.
- Store every candidate before filtering.
- Retrieve recent videos through the channel uploads playlist.
- Do not use search.list to fetch each channel’s videos.
- Fetch video statistics in batches.
- Make discovery idempotent and resumable.

## Normalized creator fields

id, platform, external_id, name, handle, profile_url, description,
followers, followers_source, uploads_playlist_id, niche, content_themes,
content_style, audience_type, engagement_rate, engagement_method,
engagement_sample_size, engagement_calculated_at, contact_email,
email_status, email_source_url, website, instagram_url, audience_age,
audience_gender, audience_geography, creator_country, fit_score,
fit_status, fit_components, fit_reasons, qualification_status,
qualification_reason, first_seen_at, last_refreshed_at, refresh_due_at,
last_error, created_at, updated_at

## Filtering

Hard gates produce FAIL with explicit reasons:

- missing or hidden subscriber count
- subscriber count outside 5,000–100,000
- no public videos
- no upload within configurable recent_upload_days
- estimated engagement below configurable minimum_engagement_rate

Otherwise calculate a 100-point fit score:

- audience size: 20
- niche relevance: 25
- content relevance: 20
- engagement: 20
- activity: 10
- geography: 5

Email availability must never affect fit_score.
It is a separate contactable flag.

Use word-boundary matching for niche terms.
Do not use naive substring checks such as `"ai" in text`.

## Engagement

Use the latest maximum 10 public videos.
Exclude videos with zero/missing views or hidden likes.
Use: `(avg likes + avg comments) / avg views * 100`
Store sample size, method, and timestamp.
Call it an approximate public engagement estimate.

## Enrichment

Only enrich PASS and REVIEW creators.
Extract emails from public channel descriptions and creator-linked public
websites.
Respect robots.txt where practical.
Use timeout and response-size limits.
Allow only public HTTP/HTTPS hosts.
Block localhost and private IP ranges.
Do not submit forms or bypass private contact workflows.
Reject asset-like emails such as x@2x.png.
Store email source.
Use Not Found for missing fields.
Do not invent demographics.

## AI

Use three independent structured tasks:

1. creator classification
2. creator/brand fit explanation
3. personalized email and DM generation

All LLM output must be JSON and validated with Pydantic.
Use only supplied creator evidence.
Do not invent recent content, audience data, metrics, names, or claims.
Validate email length: 60–90 words.
Validate DM length: 15–30 words.
Reject unresolved placeholders.
Validate that content references appear in supplied themes or recent titles.
Retry invalid output up to 3 times with a specific validation error.
Use an offline fallback composer if the LLM is unavailable.
Mark fallback output as offline-fallback.

## Approval

A generated message begins as PENDING_REVIEW.
Approval requires:

- valid public email
- valid message
- no unresolved placeholders
- no suppression match
- non-stale creator profile
- no prior successful outreach
- explicit reviewer action

Approval and sending must be separate operations.

## Sending

Use a sender interface with:

- DryRunSender
- GmailSender, optional

Default mode is dry_run.
Dry run never calls Gmail and records SIMULATED.
Test mode may only send to SEND_TEST_EMAIL_TO.
Live mode requires explicit configuration and approval.
Always check duplicate outreach by influencer and normalized email.
Use a deterministic idempotency key.
Use an SQLite unique or partial unique index as a backstop.
Instagram DMs are exported to a manual queue and never auto-sent.

## Testing

Mock all network calls.
Test:

- normalization
- deduplication
- quota reservation
- cache hits
- pagination budgeting
- API error classification
- engagement calculation
- niche word-boundary matching
- hard gates
- fit scoring
- email extraction
- message validation
- approval blocking
- dry-run not calling Gmail
- duplicate prevention
- CSV export

## Coding rules

- Inspect existing files before changing them.
- Do not overwrite working code unnecessarily.
- Implement one coherent phase at a time.
- After each phase, run tests.
- Fix failures before proceeding.
- Keep functions small and typed.
- Use UTC timestamps internally.
- Use parameterized SQL.
- Do not add UI until CLI/backend behavior is tested.
- Do not introduce LangChain or complex agent frameworks.
- Do not add fake data to production exports.
- Synthetic fixtures may exist only under tests/fixtures.
- Update README whenever behavior or setup changes.

## Suggested execution order

1. Global project spec
2. Repository audit
3. Foundation
4. SQLite database
5. YouTube API/cache
6. Normalization/engagement
7. Heuristics/scoring
8. Enrichment
9. LLM classification
10. Personalization
11. Approval queue
12. Dry-run/Gmail
13. Instagram queue
14. CLI orchestration
15. Integration tests
16. README
17. Final audit

After every phase: run relevant tests, show changed files and exact commands,
report failures honestly, and do not proceed until that phase is green.
