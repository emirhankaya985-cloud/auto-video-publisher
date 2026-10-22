"""Durable one-shot publication batch ledger; SQLite is for tests/dry-runs only."""
from __future__ import annotations
import sqlite3, uuid
import threading
from datetime import datetime, timezone

STATUSES = {"pending", "claimed", "submitted", "confirmed", "failed", "unknown"}

class BatchLedger:
    def __init__(self, path=":memory:"):
        self.db = sqlite3.connect(path, isolation_level=None, check_same_thread=False)
        self._claim_lock = threading.Lock()
        self.db.execute("PRAGMA busy_timeout=5000")
        self.db.executescript("""CREATE TABLE IF NOT EXISTS batches(batch_id TEXT PRIMARY KEY,created_at TEXT NOT NULL,closed_at TEXT); CREATE TABLE IF NOT EXISTS targets(batch_id TEXT NOT NULL,account TEXT NOT NULL,platform TEXT NOT NULL,drive_file_id TEXT NOT NULL,drive_folder_id TEXT NOT NULL,status TEXT NOT NULL CHECK(status IN ('pending','claimed','submitted','confirmed','failed','unknown')),claim_token TEXT,remote_id TEXT,remote_url TEXT,error TEXT,updated_at TEXT NOT NULL,PRIMARY KEY(batch_id,account,platform),UNIQUE(account,platform,drive_file_id),FOREIGN KEY(batch_id) REFERENCES batches(batch_id));""")
    @staticmethod
    def new_id(): return "batch-" + uuid.uuid4().hex
    def create(self, targets):
        bid, now = self.new_id(), datetime.now(timezone.utc).isoformat()
        with self.db:
            self.db.execute("INSERT INTO batches VALUES(?,?,NULL)",(bid,now))
            for t in targets: self.db.execute("INSERT INTO targets(batch_id,account,platform,drive_file_id,drive_folder_id,status,updated_at) VALUES(?,?,?,?,?,'pending',?)",(bid,t['account'],t['platform'],t['drive_file_id'],t['drive_folder_id'],now))
        return bid
    def claim(self,batch_id,account,platform):
        token, now = uuid.uuid4().hex, datetime.now(timezone.utc).isoformat()
        with self._claim_lock:
            cur=self.db.execute("UPDATE targets SET status='claimed',claim_token=?,updated_at=? WHERE batch_id=? AND account=? AND platform=? AND status='pending'",(token,now,batch_id,account,platform))
            return token if cur.rowcount==1 else None
    def finish(self,batch_id,account,platform,status,remote_id=None,remote_url=None,error=None):
        if status not in STATUSES-{"pending","claimed"}: raise ValueError(status)
        self.db.execute("UPDATE targets SET status=?,remote_id=?,remote_url=?,error=?,updated_at=? WHERE batch_id=? AND account=? AND platform=?",(status,remote_id,remote_url,error,datetime.now(timezone.utc).isoformat(),batch_id,account,platform))
    def close(self,batch_id): self.db.execute("UPDATE batches SET closed_at=? WHERE batch_id=?",(datetime.now(timezone.utc).isoformat(),batch_id))
    def rows(self,batch_id): return self.db.execute("SELECT * FROM targets WHERE batch_id=? ORDER BY account,platform",(batch_id,)).fetchall()
