"""One concise Telegram receipt for confirmed cross-account Meta actions only.

Never sends notifications for dry-run, reservations, unsupported saves, or
unverified provider acknowledgements. No Meta writes are performed here.
"""
from collections import defaultdict
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
    groups = defaultdict(lambda: {"recipients": set(), "posts": set(), "count": 0})
    for task in plan:
        if not isinstance(task, dict) or task.get("operation") != "like":
            continue
        platform, actor, owner = task.get("platform"), str(task.get("actor")), str(task.get("owner"))
        if platform not in ("facebook", "instagram") or not actor.isdecimal() or not owner.isdecimal() or actor == owner:
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
    return groups


def message(groups, run_id):
    if not groups:
        return None
    lines = ["Doğrulanmış Meta beğenileri (Graph API başarı alındısı):"]
    for (actor, platform), result in sorted(groups.items()):
        owners = ", ".join(sorted(result["recipients"]))
        lines.append(f"• {actor} / {platform}: {result['count']} beğeni → {owners}")
    lines.extend(["Kaydetme / yeniden paylaşım: API alındısı yoksa başarı sayılmaz.",
                  "Bu özet 'tüm hesapları beğendi' anlamına gelmez.",
                  f"https://github.com/emirhankaya985-cloud/auto-video-publisher/actions/runs/{run_id}"])
    return "\n".join(lines)


def main():
    run_id = os.getenv("GITHUB_RUN_ID", "")
    if os.getenv("ENGAGEMENT_MODE") not in ("apply", "single_like") or os.getenv("ENGAGEMENT_RESULT_ARCHIVED") != "true":
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
    receipt = send_telegram("✅ Meta etkileşim alındısı", body)
    print(json.dumps({"status": "notified", "accepted_likes": sum(x["count"] for x in groups.values()),
                      "telegram_server_ack": receipt.get("server_ack") is True,
                      "phone_delivery_verified": False}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
