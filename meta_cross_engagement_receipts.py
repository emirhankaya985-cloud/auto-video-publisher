"""One concise Telegram receipt for confirmed cross-account and owner Meta likes only.

Never sends notifications for dry-run, reservations, unsupported saves, or
unverified provider acknowledgements. No Meta writes are performed here.
"""
from collections import defaultdict
from html import escape
import json
import os
from pathlib import Path

from telegram_notifications import send_telegram

LEDGER = Path("cross-engagement/engagement.json")
REPORT = Path("cross-engagement/report.json")
PLAN = Path("cross-engagement/plan.json")


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


def message(groups, run_id):
    if not groups:
        return None
    counts = defaultdict(lambda: {"likes": 0, "self": 0})
    for result in groups.values():
        for row in result["rows"]:
            item = counts[(row["actor"], row["platform"], row["owner"])]
            item["likes"] += 1
            item["self"] += int(row["self_like"])
    all_accounts = sorted({
        name for (platform, _account_id), name in names.items()
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
    body = "\n".join([
        "Doğrulanmış Meta beğenileri — her satır beğenen hesabı ve hedef hesabı gösterir.",
        "<pre>" + escape("\n".join(table)) + "</pre>",
        f"Toplam: {confirmed} beğeni | Çapraz: {confirmed - self_likes} | "
        f"Kendi gönderisi: {self_likes}",
        "Yalnızca Graph API tarafından kabul edilmiş beğeniler listelenir.",
        "Kaydetme / yeniden paylaşım API onayı yoksa başarılı sayılmaz.",
        f"https://github.com/emirhankaya985-cloud/auto-video-publisher/actions/runs/{run_id}",
    ])
    return body


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
    groups = verified_batch(json.loads(LEDGER.read_text(encoding="utf-8")),
                            json.loads(PLAN.read_text(encoding="utf-8")), run_id, names)
    body = message(groups, run_id)
    if body is None:
        print('{"status":"no_accepted_likes_no_message"}')
        return 0
    # Attempt only once. Telegram server ack is not phone delivery proof.
    receipt = send_telegram("✅ Meta beğeni tablosu", body, parse_mode="HTML")
    print(json.dumps({"status": "notified", "accepted_likes": sum(x["count"] for x in groups.values()),
                      "telegram_server_ack": receipt.get("server_ack") is True,
                      "phone_delivery_verified": False}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
