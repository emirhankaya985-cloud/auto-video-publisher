"""One concise Telegram receipt for confirmed cross-account and owner Meta likes only.

Never sends notifications for dry-run, reservations, unsupported saves, or
unverified provider acknowledgements. No Meta writes are performed here.
"""
from collections import defaultdict
from html import escape
import json
import os
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo

from telegram_notifications import send_telegram

LEDGER = Path("cross-engagement/engagement.json")
REPORT = Path("cross-engagement/report.json")
PLAN = Path("cross-engagement/plan.json")
ALERT = Path("cross-engagement/no-like-alert.json")


def verified_batch(ledger, plan, run_id, names):
    if not isinstance(ledger, dict) or not isinstance(ledger.get("actions"), dict):
        raise RuntimeError("engagement_ledger_unavailable")
    if not isinstance(plan, list) or not run_id.isdecimal():
        raise RuntimeError("engagement_plan_unavailable")
    from meta_cross_engagement import key
    groups = defaultdict(lambda: {"recipients": set(), "posts": set(), "count": 0, "self_count": 0, "rows": []})
    for task in plan:
        if not isinstance(task, dict) or task.get("operation") != "like":
            continue
        platform, actor, owner = task.get("platform"), str(task.get("actor")), str(task.get("owner"))
        if platform not in ("facebook", "instagram") or not actor.isdecimal() or not owner.isdecimal():
            raise RuntimeError("invalid_accepted_action_identity")
        row = ledger["actions"].get(key(task))
        if not isinstance(row, dict):
            continue
        if (row.get("run_id") != run_id or row.get("status") != "accepted"
                or row.get("api_ack") is not True or str(row.get("post_id")) != str(task.get("post_id"))
                or row.get("actor") != actor or row.get("owner") != owner
                or row.get("operation") != "like" or row.get("platform") != platform):
            continue
        actor_name = names.get((platform, actor))
        owner_name = names.get((platform, owner))
        if not actor_name or not owner_name:
            raise RuntimeError("accepted_actor_identity_unverified")
        group = groups[(actor_name, platform)]
        group["recipients"].add(owner_name)
        group["posts"].add(str(task["post_id"]))
        group["count"] += 1
        group["rows"].append({
            "actor": actor_name,
            "platform": platform,
            "owner": owner_name,
            "post_id": str(task["post_id"]),
            "self_like": actor == owner,
        })
        if actor == owner:
            group["self_count"] += 1
    return groups


def message(groups, run_id, names):
    if not groups:
        return None
    counts = defaultdict(lambda: {"likes": 0, "self": 0})
    for result in groups.values():
        for row in result["rows"]:
            item = counts[(row["actor"], row["platform"], row["owner"])]
            item["likes"] += 1
            item["self"] += int(row["self_like"])
    # The verified-actor map is authoritative for the complete account list.
    # A zero-like account must not disappear merely because another account
    # received the only accepted Graph ACK in this batch.
    all_accounts = sorted({
        name for (platform, _provider_id), name in names.items()
        if platform in ("facebook", "instagram")
    }, key=str.casefold)
    rows = [
        ("BEĞENEN HESAP", "PLATFORM", "BEĞENDİĞİ HESAP", "ADET", "KENDİ?"),
    ]
    for actor in all_accounts:
        for platform in ("facebook", "instagram"):
            platform_rows = [
                (owner, value) for (liker, row_platform, owner), value in counts.items()
                if liker == actor and row_platform == platform
            ]
            if platform_rows:
                for owner, value in sorted(platform_rows, key=lambda item: item[0].casefold()):
                    rows.append((actor, platform, owner, str(value["likes"]),
                                 "Evet" if value["self"] else "Hayır"))
            else:
                rows.append((actor, platform, "Henüz doğrulanmış beğeni yok", "0", "—"))
    widths = [20, 10, 20, 5, 6]
    table = [" | ".join(cell.ljust(width) for cell, width in zip(row, widths))
             for row in rows]
    confirmed = sum(result["count"] for result in groups.values())
    self_likes = sum(result["self_count"] for result in groups.values())
    detail_rows = [
        f"{actor} / {platform}: {value['likes']} beğeni → {owner} "
        f"(kendi gönderisi: {value['self']})"
        for (actor, platform, owner), value in sorted(counts.items())
    ]
    body = "\n".join([
        "Doğrulanmış Meta beğenileri — her satır beğenen hesabı ve hedef hesabı gösterir.",
        "Durum: tüm hesapları ve iki platformu listeler; 0 yalnızca bu çalıştırmada doğrulanmış beğeni olmadığını belirtir.",
        "<pre>" + escape("\n".join(table)) + "</pre>",
        "Ayrıntı: " + "; ".join(detail_rows),
        f"Toplam: {confirmed} beğeni | Çapraz: {confirmed - self_likes} | "
        f"Kendi gönderisi: {self_likes}",
        "Yalnızca Graph API tarafından kabul edilmiş beğeniler listelenir.",
        "Kaydetme / yeniden paylaşım API onayı yoksa başarılı sayılmaz.",
        f"https://github.com/emirhankaya985-cloud/auto-video-publisher/actions/runs/{run_id}",
    ])
    return body


def no_like_alert(report, ledger, plan, run_id):
    """Report zero confirmed likes without implying that a POST was attempted."""
    if not isinstance(report, dict) or not isinstance(ledger, dict) or not isinstance(plan, list):
        raise RuntimeError("engagement_outcome_unavailable")
    from meta_cross_engagement import key
    planned = report.get("planned")
    if type(planned) is not int or planned != len(plan):
        raise RuntimeError("engagement_plan_count_mismatch")
    statuses = []
    verified_accepted = False
    for task in plan:
        if not isinstance(task, dict) or task.get("operation") != "like":
            continue
        row = ledger.get("actions", {}).get(key(task))
        if not isinstance(row, dict) or row.get("run_id") != run_id:
            raise RuntimeError("engagement_result_unavailable")
        statuses.append(row.get("status"))
        if (row.get("status") == "accepted" and row.get("api_ack") is True
                and str(row.get("post_id")) == str(task.get("post_id"))
                and row.get("actor") == str(task.get("actor"))
                and row.get("owner") == str(task.get("owner"))
                and row.get("platform") == task.get("platform")
                and row.get("operation") == "like"):
            verified_accepted = True
    if verified_accepted:
        return None
    category = "no_plan" if planned == 0 else "unconfirmed"
    if category == "no_plan":
        reason = "Bu turda uygun ve doğrulanmış yeni beğeni hedefi bulunamadı; beğeni denemesi yapılmadı."
    elif "uncertain" in statuses:
        reason = "Beğeni sonucu belirsiz. Çift işlem riskinden dolayı otomatik tekrar yapılmadı."
    else:
        reason = "Planlanan beğenilerden hiçbiri Graph API tarafından kabul edilmiş olarak doğrulanmadı."
    day = datetime.now(ZoneInfo("Europe/Istanbul")).date().isoformat()
    artifact_name = f"cross-engagement-no-like-{day}-{category}"
    body = (f"<b>⚠️ Meta beğeni durumu</b>\n{reason}\n"
            f"Planlanan: {planned} | Doğrulanan: 0\n"
            f"Ayrıntı: https://github.com/emirhankaya985-cloud/auto-video-publisher/actions/runs/{run_id}\n"
            "Aynı durum için bugün yeniden bildirim gönderilmeyecek.")
    return artifact_name, body, category


def alert_already_archived(name):
    """Fail closed when GitHub alert history cannot be verified."""
    from meta_cross_engagement import github
    payload = github(f"actions/artifacts?per_page=100&name={name}").json()
    artifacts = payload.get("artifacts") if isinstance(payload, dict) else None
    if (not isinstance(artifacts, list) or type(payload.get("total_count")) is not int
            or payload["total_count"] != len(artifacts)):
        raise RuntimeError("engagement_alert_history_unavailable")
    return any(item.get("name") == name and item.get("expired") is False
               for item in artifacts if isinstance(item, dict))


def mark_alert_archived(name, category, run_id):
    ALERT.parent.mkdir(parents=True, exist_ok=True)
    ALERT.write_text(json.dumps({"name": name, "category": category,
                                 "run_id": run_id}, sort_keys=True), encoding="utf-8")
    output = os.getenv("GITHUB_OUTPUT")
    if output:
        with open(output, "a", encoding="utf-8") as handle:
            handle.write(f"alert_artifact_name={name}\n")


def main():
    run_id = os.getenv("GITHUB_RUN_ID", "")
    if os.getenv("ENGAGEMENT_MODE") not in ("apply", "single_like", "account_batch") or os.getenv("ENGAGEMENT_RESULT_ARCHIVED") != "true":
        print('{"status":"no_verified_actions_no_message"}')
        return 0
    report = json.loads(REPORT.read_text(encoding="utf-8"))
    if report.get("mode") != "apply":
        print('{"status":"dry_run_no_message"}')
        return 0
    from meta_auth_loader import load_meta_auth
    discovered = load_meta_auth()
    names = {}
    for page in discovered["pages"]:
        if str(page["page_id"]).isdecimal():
            names[("facebook", str(page["page_id"]))] = page["page_name"]
        if str(page.get("instagram_id") or "").isdecimal():
            names[("instagram", str(page["instagram_id"]))] = page["page_name"]
    ledger = json.loads(LEDGER.read_text(encoding="utf-8"))
    plan = json.loads(PLAN.read_text(encoding="utf-8"))
    groups = verified_batch(ledger, plan, run_id, names)
    body = message(groups, run_id, names)
    if body is None:
        alert = no_like_alert(report, ledger, plan, run_id)
        if alert is None:
            print('{"status":"no_alert_accepted_action_present"}')
            return 0
        name, body, category = alert
        try:
            if alert_already_archived(name):
                print('{"status":"no_like_alert_already_sent_today"}')
                return 0
        except (RuntimeError, ValueError, KeyError, OSError):
            print('{"status":"no_like_alert_history_unavailable"}')
            return 0
        receipt = send_telegram("⚠️ Meta beğeni atılmadı", body, parse_mode="HTML")
        if receipt.get("server_ack") is True:
            mark_alert_archived(name, category, run_id)
        print(json.dumps({"status": "no_like_alert_attempted",
                          "category": category,
                          "telegram_server_ack": receipt.get("server_ack") is True,
                          "phone_delivery_verified": False}))
        return 0
    # Attempt only once. Telegram server ack is not phone delivery proof.
    receipt = send_telegram("✅ Meta beğeni tablosu", body, parse_mode="HTML")
    print(json.dumps({"status": "notified", "accepted_likes": sum(x["count"] for x in groups.values()),
                      "telegram_server_ack": receipt.get("server_ack") is True,
                      "phone_delivery_verified": False}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
