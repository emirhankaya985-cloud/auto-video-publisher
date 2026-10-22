CREATE TABLE IF NOT EXISTS batches (batch_id TEXT PRIMARY KEY, created_at TEXT NOT NULL, expires_at TEXT NOT NULL, closed_at TEXT);
CREATE TABLE IF NOT EXISTS targets (
  batch_id TEXT NOT NULL, account TEXT NOT NULL, platform TEXT NOT NULL,
  drive_file_id TEXT NOT NULL, drive_folder_id TEXT NOT NULL,
  status TEXT NOT NULL CHECK(status IN ('pending','claimed','submitted','confirmed','failed','unknown')),
  claim_token TEXT, remote_id TEXT, remote_url TEXT, error TEXT, action_run_id TEXT,
  updated_at TEXT NOT NULL, PRIMARY KEY(batch_id, account, platform),
  UNIQUE(account, platform, drive_file_id), FOREIGN KEY(batch_id) REFERENCES batches(batch_id)
);
CREATE INDEX IF NOT EXISTS idx_targets_claim ON targets(batch_id,account,platform,status);
