-- Additive only: dedicated Buffer tables; never touches existing publication history.
CREATE TABLE IF NOT EXISTS buffer_x_channels (
  channel_key TEXT PRIMARY KEY,
  channel_name TEXT NOT NULL,
  organization_id TEXT NOT NULL,
  buffer_channel_id TEXT NOT NULL UNIQUE,
  service TEXT NOT NULL CHECK (lower(service) IN ('twitter', 'x')),
  external_link TEXT,
  is_disconnected BOOLEAN NOT NULL DEFAULT FALSE,
  is_locked BOOLEAN NOT NULL DEFAULT FALSE,
  last_checked_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  active BOOLEAN NOT NULL DEFAULT FALSE
);

CREATE TABLE IF NOT EXISTS buffer_x_jobs (
  id BIGSERIAL PRIMARY KEY,
  idempotency_key TEXT NOT NULL UNIQUE,
  channel_key TEXT NOT NULL REFERENCES buffer_x_channels(channel_key),
  source_id TEXT NOT NULL,
  video_url TEXT NOT NULL,
  text TEXT NOT NULL,
  due_at TIMESTAMPTZ,
  buffer_due_at TIMESTAMPTZ,
  last_verified_at TIMESTAMPTZ,
  rights_approved BOOLEAN NOT NULL DEFAULT FALSE,
  status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN
    ('pending','submitting','uncertain','scheduled','sent','failed','held')),
  buffer_post_id TEXT UNIQUE,
  post_url TEXT,
  attempts INTEGER NOT NULL DEFAULT 0,
  retry_after TIMESTAMPTZ,
  last_error_code TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE(channel_key, source_id)
);
CREATE INDEX IF NOT EXISTS buffer_x_jobs_due_idx
  ON buffer_x_jobs(status, due_at, created_at);

CREATE TABLE IF NOT EXISTS buffer_x_api_usage (
  id BIGSERIAL PRIMARY KEY,
  requested_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  operation TEXT NOT NULL,
  http_status INTEGER,
  window_15m_remaining INTEGER,
  window_15m_reset_seconds INTEGER,
  window_24h_remaining INTEGER,
  window_24h_reset_seconds INTEGER,
  window_30d_remaining INTEGER,
  window_30d_reset_seconds INTEGER,
  outcome TEXT NOT NULL DEFAULT 'completed'
);
CREATE INDEX IF NOT EXISTS buffer_x_api_usage_requested_idx
  ON buffer_x_api_usage(requested_at);

CREATE TABLE IF NOT EXISTS buffer_x_events (
  id BIGSERIAL PRIMARY KEY,
  job_id BIGINT REFERENCES buffer_x_jobs(id),
  event_type TEXT NOT NULL,
  detail_code TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS buffer_x_notifications (
  notification_key TEXT PRIMARY KEY,
  event_type TEXT NOT NULL,
  attempted_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  ntfy_ack BOOLEAN NOT NULL DEFAULT FALSE,
  telegram_ack BOOLEAN NOT NULL DEFAULT FALSE
);
