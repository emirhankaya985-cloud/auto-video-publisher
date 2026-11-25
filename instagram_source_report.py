"""Read-only Turkish daily summary for the existing nightly report/NTFY path."""
from __future__ import annotations

import os
from datetime import date

from instagram_source_config import ROUTES, load_config

DISPLAY_NAMES = {
    "tarladaki": "Tarladaki Fasulye", "penguen": "Beyinsiz Penguen",
    "gonle": "Gönle Düşen", "daily_laugh": "Daily Laugh Lab",
    "film": "Film Mağarası", "toonzone": "ToonZone",
}
STATUS_TR = {
    "ok": "erişilebilir", "partial": "kısmi", "error": "hata",
    "unknown": "bilinmiyor", "not_checked": "kontrol edilmedi",
    "not_configured": "ayarlanmamış", "low": "kota doluluğu yüksek",
    "active": "etkin", "degraded": "sorunlu", "disabled": "kapalı",
}


def daily_source_report(local_day: str | date) -> dict:
    day = local_day.isoformat() if isinstance(local_day, date) else date.fromisoformat(str(local_day)).isoformat()
    config = load_config()
    active = any(account["enabled"] and account["auto_collection"]
                 for account in config["accounts"].values())
    result = {"day": day, "status": "disabled" if not active else "unavailable",
              "neon_status": "not_checked", "routes": {}, "manual_actions": []}
    for route in ROUTES:
        account = config["accounts"][route]
        sources = account["source_accounts"]
        needs = []
        if account["enabled"] and account["auto_collection"]:
            if account.get("config_errors"):
                needs.append("kaynak ayarındaki geçersiz alanlar düzeltilmeli")
            if not sources:
                needs.append("Instagram kaynak kullanıcı adı eklenmeli")
            if not account["collection_folder_id"]:
                needs.append("ayrı Drive alım klasörü bağlanmalı")
            if any(not (s["rights_approved"] and s["rights_evidence"].strip()
                        and s["official_api_download_allowed"]) for s in sources):
                needs.append("kaynak yayın izinleri doğrulanmalı")
        result["routes"][route] = {
            "name": DISPLAY_NAMES[route], "enabled": bool(account["enabled"] and account["auto_collection"]),
            "configured_sources": len(sources), "manual_actions": needs,
            "scanned_sources": 0, "found": 0, "downloaded": 0,
            "duplicates": 0, "archive_count": 0, "new_pool_count": 0,
            "ready_count": 0, "missing_caption_or_cover": 0,
            "api_status": "unknown", "drive_status": "unknown",
            "storage_status": "unknown", "drive_usage_bytes": None,
            "drive_limit_bytes": None, "neon_status": "not_checked", "errors": [],
        }
        result["manual_actions"].extend(f"{DISPLAY_NAMES[route]}: {item}" for item in needs)

    if not active:
        return result
    if not os.getenv("DASHBOARD_DATABASE_URL", "").strip():
        result["neon_status"] = "not_configured"
        result["status"] = "degraded"
        result["manual_actions"].append("DASHBOARD_DATABASE_URL secret doğrulanmalı")
        return result
    try:
        from instagram_source_store import connect
        with connect() as conn:
            with conn.cursor() as cur:
                cur.execute("""SELECT route,source_username,instagram_user_id,content_categories,
                  enabled,rights_approved,official_api_download_allowed,last_successful_scan_at,
                  last_scan_status,last_scan_error,total_found,total_downloaded,total_duplicates
                  FROM instagram_source_accounts
                  WHERE route=ANY(%s)""", (list(ROUTES),))
                account_rows = cur.fetchall()
                cur.execute("""SELECT route,count(DISTINCT (source_username,source_post_id)) AS found,
                  count(DISTINCT (source_username,source_post_id)) FILTER
                    (WHERE status IN ('downloaded','drive_uploaded','duplicate_reused')) AS downloaded,
                  count(DISTINCT (source_username,source_post_id)) FILTER
                    (WHERE status='duplicate_reused') AS duplicates
                  FROM instagram_source_posts
                  WHERE discovered_day=%s AND route=ANY(%s) GROUP BY route""",
                            (date.fromisoformat(day), list(ROUTES)))
                post_rows = cur.fetchall()
                cur.execute("""SELECT route,count(DISTINCT source_username),
                  CASE WHEN bool_and(api_status='ok') THEN 'ok'
                       WHEN bool_or(api_status='ok') THEN 'partial' ELSE 'error' END,
                  CASE WHEN bool_and(drive_status='ok') THEN 'ok'
                       WHEN bool_or(drive_status='ok') THEN 'partial' ELSE 'error' END,
                  CASE WHEN bool_and(storage_status='ok') THEN 'ok'
                       WHEN bool_or(storage_status='low') THEN 'low'
                       WHEN bool_or(storage_status='ok') THEN 'partial' ELSE 'unknown' END,
                  max(drive_usage_bytes),max(drive_limit_bytes)
                  FROM instagram_source_scan_runs
                  WHERE (started_at AT TIME ZONE 'Europe/Istanbul')::date=%s
                    AND route=ANY(%s) GROUP BY route""", (date.fromisoformat(day), list(ROUTES)))
                scan_rows = cur.fetchall()
                cur.execute("""SELECT route,
                  count(*) FILTER (WHERE pool='archive' AND status='available') AS archive_count,
                  count(*) FILTER (WHERE pool='new' AND status='available') AS new_count,
                  count(*) FILTER (WHERE status='available' AND drive_txt_id IS NOT NULL
                    AND drive_cover_id IS NOT NULL) AS ready_count,
                  count(*) FILTER (WHERE status='available' AND
                    (drive_txt_id IS NULL OR drive_cover_id IS NULL)) AS missing_caption_or_cover
                  FROM instagram_target_assets WHERE route=ANY(%s) GROUP BY route""",
                            (list(ROUTES),))
                pool_rows = cur.fetchall()
                cur.execute("""SELECT route,array_agg(DISTINCT error_code)
                  FROM instagram_source_scan_runs s
                  CROSS JOIN LATERAL jsonb_array_elements_text(s.error_codes) AS errors(error_code)
                  WHERE (s.started_at AT TIME ZONE 'Europe/Istanbul')::date=%s
                    AND route=ANY(%s) GROUP BY route""", (date.fromisoformat(day), list(ROUTES)))
                error_rows = cur.fetchall()
    except Exception:
        result["neon_status"] = "error"
        result["status"] = "degraded"
        result["manual_actions"].append("Neon bağlantısı ve Instagram kaynak migration durumu kontrol edilmeli")
        return result

    result["neon_status"] = "ok"
    for (route, username, instagram_user_id, categories, enabled, rights_ok, api_ok,
         last_success, last_status, last_error, total_found, total_downloaded,
         total_duplicates) in account_rows:
        entry = result["routes"].get(route)
        if entry is None:
            continue
        entry["configured_sources"] = max(entry["configured_sources"], 1)
        entry.setdefault("sources", []).append({
            "username": username, "instagram_user_id": instagram_user_id,
            "content_categories": categories or [], "enabled": bool(enabled),
            "rights_approved": bool(rights_ok),
            "official_api_download_allowed": bool(api_ok),
            "last_successful_scan_at": last_success.isoformat() if last_success else None,
            "last_scan_status": last_status, "last_scan_error": last_error,
            "total_found": int(total_found), "total_downloaded": int(total_downloaded),
            "total_duplicates": int(total_duplicates),
        })
        if enabled and rights_ok and api_ok:
            entry["authorized_sources"] = entry.get("authorized_sources", 0) + 1
        if last_error:
            entry["errors"].append(str(last_error)[:60])
    for route, found, downloaded, duplicates in post_rows:
        result["routes"][route].update(found=int(found), downloaded=int(downloaded), duplicates=int(duplicates))
    for route, scanned, api_status, drive_status, storage_status, usage, limit_bytes in scan_rows:
        result["routes"][route].update(scanned_sources=int(scanned), api_status=api_status,
                                      drive_status=drive_status, storage_status=storage_status,
                                      drive_usage_bytes=usage, drive_limit_bytes=limit_bytes,
                                      neon_status="ok")
    for route, archive_count, new_count, ready_count, missing_files in pool_rows:
        result["routes"][route].update(archive_count=int(archive_count),
                                      new_pool_count=int(new_count), ready_count=int(ready_count),
                                      missing_caption_or_cover=int(missing_files))
        if missing_files:
            result["manual_actions"].append(
                f"{DISPLAY_NAMES[route]}: eşleşen açıklama/kapak dosyaları kontrol edilmeli")
    for route, errors in error_rows:
        result["routes"][route]["errors"].extend(str(value)[:60] for value in errors or [])
    source_seen = any(row["configured_sources"] for row in result["routes"].values())
    result["status"] = "active" if source_seen else "degraded"
    return result


def format_daily_source_report(summary: dict) -> str:
    if summary.get("status") == "disabled":
        return "📥 Instagram kaynak toplama: kapalı (kaynaklar doğrulanınca etkinleştirilecek)."
    if not isinstance(summary.get("routes"), dict) or not summary["routes"]:
        manual = "; ".join(summary.get("manual_actions", []))
        return "📥 Instagram kaynak toplama: rapor alınamadı." + (f" Manuel müdahale: {manual}" if manual else "")
    lines = ["📥 INSTAGRAM KAYNAK TOPLAMA"]
    for route in ROUTES:
        item = summary["routes"][route]
        if not item["enabled"] and not item["configured_sources"]:
            lines.append(f"• {item['name']}: kapalı")
            continue
        lines.append(
            f"• {item['name']}: taranan {item['scanned_sources']} | yeni {item['found']} | "
            f"indirilen {item['downloaded']} | mükerrer {item['duplicates']} | "
            f"arşiv {item['archive_count']} | havuz {item['new_pool_count']} | "
            f"yayına hazır {item['ready_count']} | açıklama/kapak eksiği {item['missing_caption_or_cover']} | "
            f"API {STATUS_TR.get(item['api_status'], item['api_status'])} | "
            f"Drive {STATUS_TR.get(item['drive_status'], item['drive_status'])} | "
            f"Neon {STATUS_TR.get(item['neon_status'], item['neon_status'])} | "
            f"Drive alanı {STATUS_TR.get(item['storage_status'], item['storage_status'])}"
        )
        if item["drive_usage_bytes"] is not None and item["drive_limit_bytes"]:
            used_gb = item["drive_usage_bytes"] / 1_000_000_000
            limit_gb = item["drive_limit_bytes"] / 1_000_000_000
            lines.append(f"  Drive kullanımı: {used_gb:.2f}/{limit_gb:.2f} GB")
        for error in dict.fromkeys(item["errors"]):
            lines.append(f"  ⚠️ İşlem: {error}")
        for source in item.get("sources", []):
            last_scan = source["last_successful_scan_at"] or "henüz başarılı tarama yok"
            lines.append(f"  Kaynak @{source['username']}: son başarılı tarama {last_scan}; "
                         f"toplam bulunan {source['total_found']}, indirilen {source['total_downloaded']}, "
                         f"mükerrer {source['total_duplicates']}")
    if summary.get("manual_actions"):
        lines.append("Manuel müdahale: " + "; ".join(dict.fromkeys(summary["manual_actions"])))
    elif summary.get("status") == "unavailable":
        lines.append("Manuel müdahale: kaynak toplama özeti okunamadı")
    return "\n".join(lines)
