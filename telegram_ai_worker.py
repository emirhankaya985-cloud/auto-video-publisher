"""Owner-only long polling assistant. Run one instance with persistent SQLite."""
import io
import json
import os
import sqlite3
import time
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import requests

from analytics_github_history import REPOSITORY, MAX_ARCHIVE_BYTES, restore_history
from nvidia_assistant import answer, enabled
from telegram_notifications import _BOT_TOKEN, _CHAT_ID, send_telegram


def compact_history(path):
    """Expose only aggregate measurements, not video captions, IDs or tokens."""
    rows = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if row.get("entity_type") == "account" and row.get("metric") in {"snapshot_status", "lifetime_views"}:
            rows.append({k: row.get(k) for k in ("period", "measured_at", "account", "platform", "metric", "value", "status")})
    days = sorted({r["period"] for r in rows if isinstance(r["period"], str)})[-30:]
    return [r for r in rows if r["period"] in days]


def latest_evidence(directory, *, session=requests):
    """Read only the fixed production repo, workflow and main branch artifacts."""
    token = os.getenv("GITHUB_TOKEN", "")
    if not token:
        raise RuntimeError("Analytics access is not configured")
    headers = {"Authorization": "Bearer " + token, "Accept": "application/vnd.github+json"}
    base = "https://api.github.com/repos/" + REPOSITORY
    try:
        result = session.get(base + "/actions/workflows/daily_stats.yml/runs",
            headers=headers, params={"branch": "main", "status": "success", "per_page": 1},
            timeout=25, allow_redirects=False)
        if result.status_code != 200:
            raise ValueError("Report listing unavailable")
        run = result.json()["workflow_runs"][0]
        if run.get("head_branch") != "main" or run.get("conclusion") != "success":
            raise ValueError("Report identity invalid")
        artifacts = session.get(base + f"/actions/runs/{int(run['id'])}/artifacts",
            headers=headers, timeout=25, allow_redirects=False)
        if artifacts.status_code != 200:
            raise ValueError("Artifact listing unavailable")
        matches = [a for a in artifacts.json()["artifacts"]
                   if a.get("name") == "account-views-comparison" and a.get("expired") is False]
        if len(matches) != 1:
            raise ValueError("Comparison unavailable")
        data = session.get(base + f"/actions/artifacts/{int(matches[0]['id'])}/zip",
                           headers=headers, timeout=35, allow_redirects=True)
        if data.status_code != 200 or len(data.content) > MAX_ARCHIVE_BYTES:
            raise ValueError("Comparison download unavailable")
        with zipfile.ZipFile(io.BytesIO(data.content)) as archive:
            if archive.namelist() != ["account_views_comparison.json"] or archive.infolist()[0].file_size > MAX_ARCHIVE_BYTES:
                raise ValueError("Comparison layout invalid")
            comparison = json.loads(archive.read("account_views_comparison.json"))
        if not isinstance(comparison, dict) or not isinstance(comparison.get("accounts"), list) or not comparison.get("measured_at"):
            raise ValueError("Comparison invalid")
        history_path = Path(directory) / "ai-readonly-history.jsonl"
        restored = restore_history(history_path, get=session.get)
        history = compact_history(history_path) if restored["status"] == "restored" else []
        return {"fetched_at": datetime.now(timezone.utc).isoformat(),
                "report_run": run["id"], "latest_comparison": comparison,
                "archive_account_measurements": history,
                "publication_status": "Bu veri kaynağında yayın sonucu bulunmuyor."}
    except (requests.RequestException, ValueError, KeyError, TypeError, IndexError,
            zipfile.BadZipFile, OSError):
        raise RuntimeError("Verified analytics unavailable; no cached result presented as current") from None


class Worker:
    def __init__(self, database, *, evidence_loader=latest_evidence, model=answer, sender=send_telegram):
        self.chat = os.getenv("TELEGRAM_CHAT_ID", "")
        self.owner = os.getenv("TELEGRAM_AI_OWNER_ID", "")
        token = os.getenv("TELEGRAM_BOT_TOKEN", "")
        if not enabled() or not os.getenv("NVIDIA_API_KEY") or not _BOT_TOKEN.fullmatch(token) or not _CHAT_ID.fullmatch(self.chat) or not self.owner.isdecimal():
            raise RuntimeError("Assistant configuration incomplete")
        self.url = "https://api.telegram.org/bot" + token + "/"
        self.directory = Path(database).parent
        self.directory.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(database)
        self.db.execute("CREATE TABLE IF NOT EXISTS state (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        self.db.execute("CREATE TABLE IF NOT EXISTS conversation (id INTEGER PRIMARY KEY, role TEXT, content TEXT)")
        self.db.commit()
        self.load, self.model, self.send = evidence_loader, model, sender

    def offset(self):
        row = self.db.execute("SELECT value FROM state WHERE key='offset'").fetchone()
        return int(row[0]) if row else 0

    def handle(self, update):
        uid = update.get("update_id")
        if type(uid) is not int:
            return
        self.db.execute("BEGIN IMMEDIATE")
        if uid < self.offset():
            self.db.rollback()
            return
        # Persist before any external call. Crashes/uncertain send are not replayed.
        self.db.execute("INSERT OR REPLACE INTO state VALUES ('offset', ?)", (str(uid + 1),))
        self.db.commit()
        message = update.get("message", {})
        if (str(message.get("chat", {}).get("id")) != self.chat or
                str(message.get("from", {}).get("id")) != self.owner or message.get("from", {}).get("is_bot") is True):
            return
        text = message.get("text")
        if not isinstance(text, str) or not text.strip():
            return
        if text.strip() in {"/start", "/help"}:
            self.send("🤖 Sosyal medya yardımcısı", "/ozet: son ölçümün özeti\n/durum: veri tarihi\n/sifirla: sohbeti unut\nHesapların hakkında doğrudan soru da yazabilirsin.")
            return
        if text.strip() == "/sifirla":
            self.db.execute("DELETE FROM conversation")
            self.db.commit()
            self.send("🤖 Sohbet", "Sohbet geçmişi silindi. Ölçüm arşivi korundu.")
            return
        history = [{"role": r, "content": c} for r, c in self.db.execute("SELECT role,content FROM conversation ORDER BY id")]
        try:
            evidence = self.load(self.directory)
            if text.strip() == "/durum":
                reply = "Son ölçüm: " + evidence["latest_comparison"]["measured_at"] + "\nKaynak rapor: " + str(evidence["report_run"]) + "\nBu bilgi canlı anlık izlenme değildir."
            else:
                question = "Son kayıtlı ölçüm gününü, eksikleri ve günlük/haftalık farkı özetle." if text.strip() == "/ozet" else text
                reply = self.model(question, evidence, history)
        except Exception:
            self.send("🤖 Veri durumu", "Doğrulanmış veri veya yapay zekâ yanıtı şu an alınamadı. Sayı tahmin etmedim; daha sonra tekrar sorabilirsin.")
            return
        self.send("🤖 Sosyal medya yardımcısı", reply)
        self.db.executemany("INSERT INTO conversation(role,content) VALUES (?,?)", [("user", text[:3000]), ("assistant", reply[:3000])])
        self.db.execute("DELETE FROM conversation WHERE id NOT IN (SELECT id FROM conversation ORDER BY id DESC LIMIT 6)")
        self.db.commit()

    def run(self, *, session=requests):
        # Never delete somebody else's existing webhook or consume its messages.
        info = session.get(self.url + "getWebhookInfo", timeout=20, allow_redirects=False)
        payload = info.json()
        if info.status_code != 200 or payload.get("ok") is not True or payload["result"].get("url"):
            raise RuntimeError("Telegram webhook active or status unavailable; polling not started")
        while True:
            try:
                result = session.get(self.url + "getUpdates", params={"offset": self.offset(), "timeout": 25,
                    "allowed_updates": json.dumps(["message"])}, timeout=35, allow_redirects=False)
                payload = result.json()
                if result.status_code != 200 or payload.get("ok") is not True or not isinstance(payload.get("result"), list):
                    raise ValueError("Polling unavailable")
                for update in payload["result"]:
                    self.handle(update)
            except Exception:
                print("Assistant polling/delivery unavailable; no credential-bearing details logged.", flush=True)
                time.sleep(5)


if __name__ == "__main__":
    Worker(os.getenv("TELEGRAM_AI_DB", "ai-runtime/telegram.sqlite3")).run()
