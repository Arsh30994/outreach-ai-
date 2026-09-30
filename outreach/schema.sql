-- CreatorReach AI schema (SQLite). Applied by outreach.db.init_db.
-- All timestamps are UTC ISO-8601 strings.

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS schema_migrations (
    version INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    applied_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS discovery_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    queries_json TEXT NOT NULL DEFAULT '[]',
    status TEXT NOT NULL DEFAULT 'running',
    search_results INTEGER NOT NULL DEFAULT 0,
    unique_channels INTEGER NOT NULL DEFAULT 0,
    new_stored INTEGER NOT NULL DEFAULT 0,
    quota_used INTEGER NOT NULL DEFAULT 0,
    notes TEXT
);

CREATE TABLE IF NOT EXISTS influencers (
    id TEXT PRIMARY KEY,
    platform TEXT NOT NULL DEFAULT 'YouTube',
    external_id TEXT NOT NULL,
    name TEXT NOT NULL,
    handle TEXT,
    profile_url TEXT NOT NULL,
    description TEXT,
    followers INTEGER,
    followers_source TEXT NOT NULL DEFAULT 'Not Found',
    followers_hidden INTEGER NOT NULL DEFAULT 0,
    uploads_playlist_id TEXT,
    total_views INTEGER,
    video_count INTEGER,
    channel_keywords TEXT,
    niche TEXT,
    content_themes TEXT NOT NULL DEFAULT '[]',
    content_style TEXT,
    audience_type TEXT,
    classification_source TEXT,
    engagement_rate REAL,
    engagement_method TEXT NOT NULL DEFAULT 'Not Found',
    engagement_sample_size INTEGER NOT NULL DEFAULT 0,
    engagement_calculated_at TEXT,
    last_upload_at TEXT,
    contact_email TEXT NOT NULL DEFAULT 'Not Found',
    email_status TEXT NOT NULL DEFAULT 'Not Found',
    email_source_url TEXT NOT NULL DEFAULT 'Not Found',
    website TEXT NOT NULL DEFAULT 'Not Found',
    instagram_url TEXT NOT NULL DEFAULT 'Not Found',
    tiktok_url TEXT NOT NULL DEFAULT 'Not Found',
    audience_age TEXT NOT NULL DEFAULT 'Not Found',
    audience_gender TEXT NOT NULL DEFAULT 'Not Found',
    audience_geography TEXT NOT NULL DEFAULT 'Not Found',
    creator_country TEXT,
    fit_score INTEGER,
    fit_status TEXT,
    fit_components TEXT,
    fit_reasons TEXT,
    qualification_status TEXT NOT NULL DEFAULT 'DISCOVERED',
    qualification_reason TEXT,
    contactable INTEGER NOT NULL DEFAULT 0,
    discovery_run_id INTEGER REFERENCES discovery_runs(id),
    source_query TEXT,
    first_seen_at TEXT NOT NULL,
    last_refreshed_at TEXT,
    refresh_due_at TEXT,
    collected_at TEXT,
    classified_at TEXT,
    scored_at TEXT,
    enriched_at TEXT,
    last_error TEXT,
    last_error_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (platform, external_id)
);

CREATE INDEX IF NOT EXISTS idx_influencers_qualification
    ON influencers(qualification_status);
CREATE INDEX IF NOT EXISTS idx_influencers_followers
    ON influencers(followers);
CREATE INDEX IF NOT EXISTS idx_influencers_email
    ON influencers(contact_email);
CREATE INDEX IF NOT EXISTS idx_influencers_fit_status
    ON influencers(fit_status);
CREATE INDEX IF NOT EXISTS idx_influencers_updated
    ON influencers(updated_at);
CREATE INDEX IF NOT EXISTS idx_influencers_first_seen
    ON influencers(first_seen_at);

CREATE TABLE IF NOT EXISTS content_items (
    id TEXT PRIMARY KEY,
    influencer_id TEXT NOT NULL REFERENCES influencers(id) ON DELETE CASCADE,
    external_id TEXT NOT NULL,
    title TEXT NOT NULL,
    url TEXT NOT NULL,
    published_at TEXT,
    views INTEGER,
    likes INTEGER,
    comments INTEGER,
    description TEXT,
    retrieved_at TEXT NOT NULL,
    UNIQUE (influencer_id, external_id)
);

CREATE INDEX IF NOT EXISTS idx_content_influencer
    ON content_items(influencer_id);
CREATE INDEX IF NOT EXISTS idx_content_published
    ON content_items(published_at);

CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    influencer_id TEXT NOT NULL REFERENCES influencers(id) ON DELETE CASCADE,
    channel TEXT NOT NULL DEFAULT 'email',
    email_subject TEXT,
    email_body TEXT,
    instagram_dm TEXT,
    status TEXT NOT NULL DEFAULT 'PENDING_REVIEW',
    model TEXT,
    prompt_version TEXT,
    generation_method TEXT,
    evidence_used TEXT NOT NULL DEFAULT '[]',
    notes TEXT,
    reviewer TEXT,
    review_reason TEXT,
    generated_at TEXT NOT NULL,
    approved_at TEXT,
    rejected_at TEXT,
    superseded_at TEXT,
    expired_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_messages_status ON messages(status);
CREATE INDEX IF NOT EXISTS idx_messages_influencer ON messages(influencer_id);

CREATE TABLE IF NOT EXISTS outreach (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    influencer_id TEXT NOT NULL REFERENCES influencers(id),
    message_id INTEGER REFERENCES messages(id),
    channel TEXT NOT NULL DEFAULT 'email',
    intended_recipient TEXT,
    actual_recipient TEXT,
    normalized_email TEXT,
    status TEXT NOT NULL,
    detail TEXT,
    provider_message_id TEXT,
    idempotency_key TEXT NOT NULL,
    mode TEXT NOT NULL DEFAULT 'dry_run',
    created_at TEXT NOT NULL,
    UNIQUE (idempotency_key)
);

CREATE INDEX IF NOT EXISTS idx_outreach_influencer ON outreach(influencer_id);
CREATE INDEX IF NOT EXISTS idx_outreach_email ON outreach(normalized_email);
CREATE INDEX IF NOT EXISTS idx_outreach_status ON outreach(status);

-- At most one successful email outreach per influencer.
CREATE UNIQUE INDEX IF NOT EXISTS ux_outreach_success_influencer
    ON outreach(influencer_id, channel)
    WHERE status IN ('SENT', 'SIMULATED') AND channel = 'email';

-- At most one successful email outreach per normalized recipient address.
CREATE UNIQUE INDEX IF NOT EXISTS ux_outreach_success_email
    ON outreach(normalized_email, channel)
    WHERE status IN ('SENT', 'SIMULATED')
      AND channel = 'email'
      AND normalized_email IS NOT NULL
      AND normalized_email != '';

CREATE TABLE IF NOT EXISTS field_provenance (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    influencer_id TEXT NOT NULL REFERENCES influencers(id) ON DELETE CASCADE,
    field_name TEXT NOT NULL,
    field_value TEXT,
    source TEXT NOT NULL,
    retrieved_at TEXT NOT NULL,
    UNIQUE (influencer_id, field_name, source, retrieved_at)
);

CREATE INDEX IF NOT EXISTS idx_provenance_influencer
    ON field_provenance(influencer_id);

CREATE TABLE IF NOT EXISTS api_cache (
    cache_key TEXT PRIMARY KEY,
    endpoint TEXT NOT NULL,
    payload TEXT NOT NULL,
    fetched_at TEXT NOT NULL,
    expires_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_api_cache_expires ON api_cache(expires_at);

CREATE TABLE IF NOT EXISTS quota_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    endpoint TEXT NOT NULL,
    units INTEGER NOT NULL,
    reserved INTEGER NOT NULL DEFAULT 1,
    search_call INTEGER NOT NULL DEFAULT 0,
    cache_hit INTEGER NOT NULL DEFAULT 0,
    discovery_run_id INTEGER REFERENCES discovery_runs(id),
    detail TEXT,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_quota_created ON quota_events(created_at);
CREATE INDEX IF NOT EXISTS idx_quota_endpoint ON quota_events(endpoint);

CREATE TABLE IF NOT EXISTS suppression_list (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kind TEXT NOT NULL,
    value TEXT NOT NULL,
    reason TEXT,
    created_at TEXT NOT NULL,
    UNIQUE (kind, value)
);

CREATE TABLE IF NOT EXISTS instagram_dm_queue (
    queue_id INTEGER PRIMARY KEY AUTOINCREMENT,
    influencer_id TEXT NOT NULL REFERENCES influencers(id),
    message_id INTEGER REFERENCES messages(id),
    creator_name TEXT NOT NULL,
    instagram_url TEXT NOT NULL,
    dm_text TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'PENDING_MANUAL_REVIEW',
    created_at TEXT NOT NULL,
    manually_sent_at TEXT,
    notes TEXT,
    UNIQUE (influencer_id, message_id)
);
