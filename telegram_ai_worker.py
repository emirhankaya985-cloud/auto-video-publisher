"""Owner-only long polling assistant. Run one instance with persistent SQLite."""
import io
import json
import os
import sqlite3
import time
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

from analytics_github_history import REPOSITORY, MAX_ARCHIVE_BYTES, restore_history
from nvidia_assistant import answer, enabled
from telegram_notifications import (STATISTICS_BUTTON, THREADS_STATISTICS_BUTTON,
                                    STATISTICS_KEYBOARD, _BOT_TOKEN, _CHAT_ID, send_telegram)
from telegram_status import load_status
from views_comparison import number


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


def latest_comparison(*, session=requests):
    """Read the newest valid main-branch report, ignoring incomplete artifacts."""
    token = os.getenv("GITHUB_TOKEN", "")
    if not token:
        raise RuntimeError("Analytics access is not configured")
    headers = {"Authorization": "Bearer " + token, "Accept": "application/vnd.github+json"}
    base = "https://api.github.com/repos/" + REPOSITORY
    try:
        result = session.get(base + "/actions/workflows/daily_stats.yml/runs",
            headers=headers, params={"branch": "main", "status": "success", "per_page": 5},
            timeout=25, allow_redirects=False)
        if result.status_code != 200:
            raise ValueError("Report listing unavailable")
        runs = result.json().get("workflow_runs")
        if not isinstance(runs, list):
            raise ValueError("Report list malformed")
        for run in runs:
            if not isinstance(run, dict) or run.get("head_branch") != "main" or run.get("conclusion") != "success":
                continue
            if type(run.get("id")) is not int:
                continue
            artifacts = session.get(base + f"/actions/runs/{run['id']}/artifacts",
                headers=headers, timeout=25, allow_redirects=False)
            if artifacts.status_code != 200:
                continue
            names = artifacts.json().get("artifacts")
            if not isinstance(names, list):
                continue
            matches = [a for a in names if isinstance(a, dict) and
                       a.get("name") == "account-views-comparison" and a.get("expired") is False
                       and type(a.get("id")) is int]
            if len(matches) != 1:
                continue
            data = session.get(base + f"/actions/artifacts/{int(matches[0]['id'])}/zip",
                headers=headers, timeout=35, allow_redirects=True)
            if data.status_code != 200 or len(data.content) > MAX_ARCHIVE_BYTES:
                continue
            try:
                with zipfile.ZipFile(io.BytesIO(data.content)) as archive:
                    if archive.namelist() != ["account_views_comparison.json"] or archive.infolist()[0].file_size > MAX_ARCHIVE_BYTES:
                        continue
                    comparison = json.loads(archive.read("account_views_comparison.json"))
            except (zipfile.BadZipFile, ValueError, TypeError, KeyError):
                continue
            if (isinstance(comparison, dict) and isinstance(comparison.get("accounts"), list)
                    and isinstance(comparison.get("measured_at"), str) and comparison["measured_at"]):
                return run["id"], comparison
        raise ValueError("No valid current report archive")
    except (requests.RequestException, ValueError, KeyError, TypeError, IndexError,
            zipfile.BadZipFile, OSError):
        raise RuntimeError("Verified analytics unavailable; no cached result presented as current") from None


def latest_evidence(directory, *, session=requests):
    run_id, comparison = latest_comparison(session=session)
    try:
        history_path = Path(directory) / "ai-readonly-history.jsonl"
        restored = restore_history(history_path, get=session.get)
        history = compact_history(history_path) if restored["status"] == "restored" else []
        return {"fetched_at": datetime.now(timezone.utc).isoformat(),
                "report_run": run_id, "latest_comparison": comparison,
                "archive_account_measurements": history,
                "publication_status": "Bu veri kaynağında yayın sonucu bulunmuyor."}
    except (requests.RequestException, ValueError, KeyError, TypeError, IndexError,
            zipfile.BadZipFile, OSError):
        raise RuntimeError("Verified analytics unavailable; no cached result presented as current") from None


def _statistics_totals(platforms, followers):
    """Missing platforms must not masquerade as a complete growth calculation."""
    expected = len(platforms)
    measured = [part for part in platforms if isinstance(part, dict)
                and type(part.get("total")) is int and part["total"] >= 0]
    total = sum(part["total"] for part in measured) if measured else None
    totals = [number(total)]
    for period in ("daily", "weekly"):
        deltas = [(part.get(period) or {}).get("delta") for part in measured]
        comparable = (expected > 0 and len(measured) == expected
                      and all(type(delta) is int for delta in deltas))
        totals.append(number(sum(deltas)) if comparable else "N/A")
    counted = [value for value in followers if type(value) is int and value >= 0]
    follower_total = sum(counted) if counted else None
    return [
        f"İzlenme ({len(measured)}/{expected}): {' / '.join(totals)}",
        f"Takipçi + abone ({len(counted)}/{expected}): {number(follower_total)}",
    ]


def report_freshness(measured, *, now=None):
    """Timestamp and staleness warning, never imply an old archive is live."""
    now = now or datetime.now(ZoneInfo("Europe/Istanbul"))
    if measured.tzinfo is None:
        raise ValueError("Unzoned measurement")
    age = (now - measured.astimezone(now.tzinfo)).total_seconds()
    if age > 36 * 3600:
        return "⚠️ Son doğrulanmış rapor 36 saatten eski; güncel görüntülenme/takipçi N/A."
    if age < -600:
        return "⚠️ Rapor tarihi gelecekte görünüyor; güncel sayılmadı."
    return None


def load_statistics(*, session=requests):
    """Render the latest successful nightly measurement without collecting new data."""
    try:
        run_id, comparison = latest_comparison(session=session)
        measured = datetime.fromisoformat(comparison["measured_at"])
        if measured.tzinfo is None or not comparison["accounts"]:
            raise ValueError("Measurement unavailable")
        measured = measured.astimezone(ZoneInfo("Europe/Istanbul"))
        warning = report_freshness(measured)
        lines = [f"Son arşiv ölçümü: {measured:%d.%m.%Y %H:%M} TRT",
                 "İzlenme · toplam / 1 günlük artış / 7 günlük artış"]
        if warning:
            lines.append(warning)
        followers = {(row["account"], row["platform"]): row.get("followers")
                     for row in comparison.get("followers", [])}
        all_platforms = []
        all_followers = []
        for row in comparison["accounts"]:
            account = row["account"]
            platforms = row.get("platforms", [])
            if not platforms:
                values = (row["total"], row["daily"]["delta"], row["weekly"]["delta"])
                lines.append(f"{account}: {' / '.join(number(value) for value in values)}")
                continue
            lines.extend(["", account])
            for part in platforms:
                platform = part["platform"]
                count = followers.get((account, platform))
                label = "abone" if platform == "YouTube" else "takipçi"
                values = (part["total"], part["daily"]["delta"], part["weekly"]["delta"])
                lines.append(f"• {platform}: {' / '.join(number(value) for value in values)}"
                             f" · {number(count)} {label}")
            counts = [followers.get((account, part["platform"])) for part in platforms]
            lines.extend(_statistics_totals(platforms, counts))
            all_platforms.extend(platforms)
            all_followers.extend(counts)
        if all_platforms:
            lines.extend(["", "Genel toplam", *_statistics_totals(all_platforms, all_followers),
                          "", "Threads: video gönderisi görüntülenmeleri. Takipçi ve abone toplamı tekil kişi saymaz."])
        lines.extend(["", "N/A: veri veya karşılaştırılabilir geçmiş eksik.",
                      f"https://github.com/{REPOSITORY}/actions/runs/{int(run_id)}"])
        return "\n".join(lines)
    except (RuntimeError, KeyError, TypeError, ValueError, AttributeError):
        return "İstatistik arşivi şu anda okunamadı. Daha sonra tekrar deneyebilirsin."



def load_threads_statistics(*, session=requests):
    """Only Threads rows from the verified nightly archive; no platform writes."""
    try:
        run_id, comparison = latest_comparison(session=session)
        measured = datetime.fromisoformat(comparison["measured_at"])
        if measured.tzinfo is None or not isinstance(comparison.get("accounts"), list):
            raise ValueError("Measurement unavailable")
        measured = measured.astimezone(ZoneInfo("Europe/Istanbul"))
        followers = {(r.get("account"), r.get("platform")): r.get("followers")
                     for r in comparison.get("followers", []) if isinstance(r, dict)}
        lines = [f"🧵 Threads — son ölçüm: {measured:%d.%m.%Y %H:%M} TRT",
                 "Video görüntülenmeleri: toplam / 1 gün / 7 gün"]
        warning = report_freshness(measured)
        if warning:
            lines.append(warning)
        found = 0
        for account in comparison["accounts"]:
            if not isinstance(account, dict) or not isinstance(account.get("platforms"), list):
                continue
            for part in account["platforms"]:
                if not isinstance(part, dict) or part.get("platform") != "Threads":
                    continue
                found += 1
                daily = part.get("daily") or {}
                weekly = part.get("weekly") or {}
                total = part.get("total")
                values = (total,
                          daily.get("delta") if isinstance(daily, dict) else None,
                          weekly.get("delta") if isinstance(weekly, dict) else None)
                follower = followers.get((account.get("account"), "Threads"))
                lines.append(f"• {str(account.get('account', 'Hesap'))[:70]}: "
                             f"{' / '.join(number(value) for value in values)}"
                             f" · {number(follower)} takipçi")
        if not found:
            lines.append("N/A: doğrulanmış raporda Threads hesabı ölçümü bulunmuyor.")
        lines.extend(["", "N/A: eksik veya karşılaştırılamayan veri; 0 varsayılmadı.",
                      "Bu sonuç anlık ölçüm değildir. Penguen yetki hatası varsa eski veri güncel sayılmaz.",
                      f"https://github.com/{REPOSITORY}/actions/runs/{int(run_id)}"])
        return "\n".join(lines)
    except (RuntimeError, KeyError, TypeError, ValueError, AttributeError):
        return "Threads istatistik arşivi şu anda doğrulanamadı. Sayı tahmin edilmedi."


class Worker:
    def __init__(self, database, *, evidence_loader=latest_evidence, model=answer, sender=send_telegram,
                 status_loader=load_status, statistics_loader=load_statistics,
                 threads_statistics_loader=load_threads_statistics):
        self.chat = os.getenv("TELEGRAM_CHAT_ID", "")
        self.owner = os.getenv("TELEGRAM_AI_OWNER_ID", "")
        token = os.getenv("TELEGRAM_BOT_TOKEN", "")
        self.status_only = os.getenv('TELEGRAM_STATUS_ONLY', 'true').lower() == 'true'
        if (not (self.status_only or (enabled() and os.getenv("NVIDIA_API_KEY")) or os.getenv("TELEGRAM_CONTROL_ENABLED", "false").lower() == "true") or not _BOT_TOKEN.fullmatch(token) or not _CHAT_ID.fullmatch(self.chat) or not self.owner.isdecimal()):
            raise RuntimeError("Assistant configuration incomplete")
        self.url = "https://api.telegram.org/bot" + token + "/"
        self.directory = Path(database).parent
        self.directory.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(database)
        self.db.execute("CREATE TABLE IF NOT EXISTS state (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        self.db.execute("CREATE TABLE IF NOT EXISTS conversation (id INTEGER PRIMARY KEY, role TEXT, content TEXT)")
        self.db.commit()
        self.load, self.model, self.send = evidence_loader, model, sender
        self.load_status = status_loader
        self.load_statistics = statistics_loader
        self.load_threads_statistics = threads_statistics_loader

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
        command = text.strip().casefold().replace("\u0307", "")
        if command in {'/stok', '/durdur', '/devam'}:
            self.send('📋 Durum', 'Bu komut kaldırıldı. /durum, /istatistik veya /threads yazabilirsin.')
            return
        if self.status_only:
            if command in {'/start', '/help'}:
                self.send('📋 Durum', '/durum: yayın durumu ve saat tablosu.\n/istatistik: tüm platformlar.\n/threads: yalnız Threads.',
                          reply_markup=STATISTICS_KEYBOARD)
            elif command in {'/durum', 'durum'}:
                try:
                    reply = self.load_status()
                except Exception:
                    reply = 'Yayın durumu şu an okunamadı. Sayı tahmin etmedim; yayın ayarları değiştirilmedi.'
                self.send('📋 Yayın durumu', reply, parse_mode='HTML', reply_markup=STATISTICS_KEYBOARD)
            elif command in {'/istatistik', 'istatistik', STATISTICS_BUTTON.casefold().replace("\u0307", "")}:
                self.send(STATISTICS_BUTTON, self.load_statistics(), reply_markup=STATISTICS_KEYBOARD)
            elif command in {'/threads', '/threads_istatistik', 'threads',
                             THREADS_STATISTICS_BUTTON.casefold().replace("\u0307", "")}:
                try:
                    reply = self.load_threads_statistics()
                except Exception:
                    reply = 'Threads arşivi şu anda okunamadı. Sayı tahmin edilmedi.'
                self.send(THREADS_STATISTICS_BUTTON, reply, reply_markup=STATISTICS_KEYBOARD)
            return
        if text.strip() in {"/start", "/help"}:
            self.send("🤖 Sosyal medya yardımcısı", "/durum: veri tarihi\n/sifirla: sohbeti unut")
            return
        if text.strip() == "/sifirla":
            self.db.execute("DELETE FROM conversation")
            self.db.commit()
            self.send("🤖 Sohbet", "Sohbet geçmişi silindi. Ölçüm arşivi korundu.")
            return
        if not (enabled() and os.getenv("NVIDIA_API_KEY")) and text.strip() not in {"/durum"}:
            self.send("🤖 Veri durumu", "AI özeti etkin değil. /durum kullanılabilir.")
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
