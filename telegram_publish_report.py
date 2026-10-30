"""Post-run Telegram summary for the 985 Meta-only video publisher.

Only confirmed post IDs from the *current* GitHub Actions run count as
successful publications. Silent no-op schedule checks generate no message.
This module never uploads video or mutates the publishing state.
"""
import json
import os
import sys
from collections import Counter
from pathlib import Path

from telegram_notifications import send_telegram, telegram_configured
from ntfy_notifications import send_ntfy
from publisher_error_journal import read_errors, record_error
import publisher_alert_history as alert_history
from datetime import timedelta

STATE_PATH = Path("link-runtime/state.json")
ALLOWED_STEP_RESULTS = {"success", "failure", "skipped", "cancelled", ""}


def publication_summary(state, run_id, *, verify_outcome="success", plan_outcome="success", publish_outcome="success"):
    """Return text and category; never claim publication from workflow status."""
    if not run_id or not run_id.isdigit():
        return None, "invalid_run_id"
    if any(result not in ALLOWED_STEP_RESULTS for result in (verify_outcome, plan_outcome, publish_outcome)):
        return None, "invalid_step_outcome"
    if not isinstance(state, dict) or not isinstance(state.get("entries"), dict):
        return None, "invalid_state"
    matched = []
    for entry in state["entries"].values():
        if isinstance(entry, dict) and str(entry.get("run_id", "")) == run_id:
            matched.append(entry)

    done = [row for row in matched
            if row.get("status") == "done" and str(row.get("post_id", "")).strip()]
    unknown = [row for row in matched if row.get("status") in {"intent", "uncertain"}]
    # A failed planning step can have left an older valid state untouched.
    failed = any(result == "failure" for result in (verify_outcome, plan_outcome, publish_outcome))
    if not failed and not unknown and not done:
        return None, "nothing_to_report"
    lines = ["🚨 985 Meta yayın uyarısı" if failed or unknown else "✅ 985 Meta video yayınları",
             f"GitHub çalışma: {run_id}"]
    if done:
        lines.append(f"✅ Yeni doğrulanan gönderi: {len(done)}")
        counts = Counter((row.get("route", "unknown"), row.get("platform", "unknown")) for row in done)
        for (route, platform), count in sorted(counts.items()):
            lines.append(f"• {route} / {platform}: {count} gönderi")
    if unknown:
        lines.append(f"⚠️ Belirsiz yükleme: {len(unknown)} (otomatik tekrar yayın yok)")
    if failed:
        lines.append("❌ Yayın iş akışı adımlarından biri başarısız.")
        safe_reasons = {"media_preparation_failed", "source_or_cover_preparation_failed",
                        "invalid_media_or_graph_request", "credentials_or_permissions",
                        "rate_limit", "meta_server_or_network",
                        "unclassified_upload_result"}
        reasons = Counter(
            row.get("failure", {}).get("reason")
            for row in matched if isinstance(row.get("failure"), dict)
            and row.get("failure", {}).get("reason") in safe_reasons
        )
        for reason, count in sorted(reasons.items()):
            lines.append(f"🧩 {reason}: {count}")
    lines.append(f"🔎 https://github.com/emirhankaya985-cloud/auto-video-publisher/actions/runs/{run_id}")
    return "\n".join(lines), "alert" if failed or unknown else "published"


ROUTE_LABELS = {
    "tarladaki": "🌱 Tarladaki Fasulye",
    "penguen": "🐧 Beyinsiz Penguen",
    "gonle": "❤️ Gönle Düşen",
    "daily_laugh": "😂 Daily Laugh Lab",
    "film": "🎬 Film Mağarası",
    "film_second": "🎞️ Filmmagrasi",
    "toonzone": "📺 ToonZone",
}
PLATFORM_LABELS = {"facebook": "Facebook", "instagram": "Instagram"}


def confirmed_posts(state, run_id):
    """Only actual post IDs created and recorded by this GitHub Actions run."""
    if not isinstance(state, dict) or not isinstance(state.get("entries"), dict):
        raise ValueError("invalid publication state")
    if not isinstance(run_id, str) or not run_id.isdigit():
        raise ValueError("invalid run ID")
    return [row for row in state["entries"].values()
            if isinstance(row, dict) and row.get("status") == "done"
            and str(row.get("run_id", "")) == run_id
            and str(row.get("post_id", "")).strip()
            and row.get("route") in ROUTE_LABELS
            and row.get("platform") in PLATFORM_LABELS]


def post_message(row, run_id):
    """Individual per-platform result; does not invent a permalink."""
    route, platform = row["route"], row["platform"]
    def safe(value, limit=96):
        return str(value or "").replace("\n", " ").replace("\r", " ").strip()[:limit]
    title = f"✅ {PLATFORM_LABELS[platform]} video yayınlandı"
    body = (f"📣 Hesap: {ROUTE_LABELS[route]}\n"
            f"📱 Platform: {PLATFORM_LABELS[platform]}\n"
            f"🎬 Video: {safe(Path(str(row.get('file') or 'Video')).name)}\n"
            f"✅ Durum: Başarılı\n"
            f"🆔 Gönderi ID: {safe(row['post_id'])}\n"
            f"🔎 https://github.com/emirhankaya985-cloud/auto-video-publisher/actions/runs/{run_id}")
    return title, body


def _prepare_durable(messages, posts, events, state, run_id, *, telegram_on, ntfy_on, base_failures, category):
    now=alert_history.now_utc()
    history=alert_history.restore()
    before=json.dumps(history,sort_keys=True)
    descriptors=alert_history.incident_descriptors(events)
    if not descriptors:
        k=alert_history.identity("incident",extra="workflow")
        descriptors={k:{"kind":"incident","route":"workflow","platform":"unknown","video":"","family":"workflow"}}
    groups=[]
    for i,(title,body) in enumerate(messages):
        if i<len(posts):
            post=posts[i]
            k=alert_history.identity("post",post["route"],post["platform"],extra=str(post["post_id"]))
            keys={k:{"kind":"post","route":post["route"],"platform":post["platform"],"video":post.get("file","")}}
        elif title=="🚨 Bildirim kanalı eksik":
            k=alert_history.identity("incident",extra="notification_configuration")
            keys={k:{"kind":"incident","route":"notifications","platform":"unknown","video":"","family":"configuration"}}
        else:
            keys=descriptors
        groups.append((title,body,keys))
    observed={k:d for _,_,keys in groups for k,d in keys.items()}
    alert_history.observe(history,observed,state,run_id,now=now)
    planned=[]
    for title,body,keys in groups:
        msg=alert_history.reserve(history,title,body,keys,run_id,now=now)
        if msg: planned.append(msg)
    refresh=not history.get("archived_at") or now-alert_history.stamp(history["archived_at"])>=timedelta(hours=24)
    archive_needed=refresh or before!=json.dumps(history,sort_keys=True)
    if archive_needed: history["archived_at"]=now.isoformat()
    if os.getenv("GITHUB_OUTPUT"):
        with open(os.environ["GITHUB_OUTPUT"],"a",encoding="utf-8") as output:
            output.write(f"alert_archive_needed={str(archive_needed).lower()}\n")
    alert_history.save(alert_history.HISTORY,history)
    alert_history.save(alert_history.PREPARED,{"run_id":run_id,"messages":planned,
        "telegram":telegram_on,"ntfy":ntfy_on,"base_failures":base_failures,
        "confirmed_posts":len(posts),"recorded_errors":len(events),"category":category})
    print(json.dumps({"status":"notification_intents_prepared","messages":len(planned),
        "duplicate_messages_suppressed":len(messages)-len(planned),"sent":0}),flush=True)
    return 0


def _send_durable():
    run_id=os.getenv("GITHUB_RUN_ID","")
    try:
        plan=alert_history.read(alert_history.PREPARED)
        history=alert_history.validate(alert_history.read(alert_history.HISTORY))
        if plan.get("run_id")!=run_id or not run_id.isdigit(): raise ValueError("intent run mismatch")
        if plan["messages"] and os.getenv("ALERT_INTENT_ARCHIVED")!="true":
            raise ValueError("durable notification intent missing")
        for msg in plan["messages"]:
            if any(history["records"][k].get("intent_run_id")!=run_id for k in msg["keys"]):
                raise ValueError("notification intent mismatch")
    except (ValueError,OSError,KeyError,TypeError):
        print('{"status":"notification_intent_unverified","sent":0}',flush=True)
        return 1
    failures=plan["base_failures"]
    acks={"telegram":0,"ntfy":0}
    run_url=f"https://github.com/emirhankaya985-cloud/auto-video-publisher/actions/runs/{run_id}"
    for msg in plan["messages"]:
        for channel in ("telegram","ntfy"):
            if not plan[channel]: continue
            # A repeated send step does not repeat an already ACKed message.
            if any(channel in history["records"][k].get("attempted_channels",[]) for k in msg["keys"]):
                if not all(channel in history["records"][k].get("server_acks",[]) for k in msg["keys"]): failures+=1
                continue
            for k in msg["keys"]:
                history["records"][k].setdefault("attempted_channels",[]).append(channel)
            alert_history.save(alert_history.HISTORY,history)
            try:
                if channel=="telegram":
                    result=send_telegram(msg["title"],msg["body"])
                else:
                    info=msg["title"].startswith("ℹ️")
                    warning=msg["title"].startswith(("🚨","⚠️"))
                    result=send_ntfy(msg["title"],msg["body"],priority=2 if info else 4 if warning else 3,
                        tags=["information_source"] if info else ["warning"] if warning else ["white_check_mark"],
                        click=run_url,timeout=20,require_ack=True)
                if result.get("server_ack") is not True: raise RuntimeError("no server ack")
                alert_history.mark_ack(history,msg,channel)
                acks[channel]+=1
            except Exception as exc:
                failures+=1
                record_error(channel+"_notification","notification_delivery_failed",error=exc)
            finally:
                alert_history.save(alert_history.HISTORY,history)
    print(json.dumps({"status":"completed" if not failures else "partial_notification_failure",
        "confirmed_posts":plan["confirmed_posts"],"recorded_errors":plan["recorded_errors"],
        "telegram_server_acks":acks["telegram"],"ntfy_server_acks":acks["ntfy"],
        "delivery_failures":failures,"phone_delivery_verified":False}),flush=True)
    return 1 if failures else 0


def main():
    if os.getenv("PUBLISH_ALERT_MODE")=="send":
        return _send_durable()
    run_id = os.getenv("GITHUB_RUN_ID", "")
    plan_outcome = os.getenv("PLAN_STEP_OUTCOME", "")
    publish_outcome = os.getenv("PUBLISH_STEP_OUTCOME", "")
    verify_outcome = os.getenv("VERIFY_STEP_OUTCOME", "")
    if plan_outcome == "skipped" and publish_outcome == "skipped" and verify_outcome != "failure":
        return 0

    telegram_on = telegram_configured()
    ntfy_on = bool(os.getenv("NTFY_TOPIC_URL", "").strip() or os.getenv("NTFY_TOPIC", "").strip())
    require_both = os.getenv("REQUIRE_DUAL_NOTIFICATIONS", "").strip().lower() == "true"
    if not telegram_on and not ntfy_on and not require_both:
        print('{"status":"notifications_not_configured"}', flush=True)
        return 0
    try:
        state = {"entries": {}}
        if STATE_PATH.is_file():
            state = json.loads(STATE_PATH.read_text(encoding="utf-8"))
        message, category = publication_summary(
            state, run_id, verify_outcome=verify_outcome,
            plan_outcome=plan_outcome, publish_outcome=publish_outcome,
        )
        if category in {"invalid_run_id", "invalid_state", "invalid_step_outcome"}:
            raise ValueError(category)
        posts = confirmed_posts(state, run_id)
        events = read_errors(run_id=run_id)
    except (ValueError, OSError, TypeError) as exc:
        print(json.dumps({"status": "notification_report_invalid_state",
                          "error_type": type(exc).__name__}), flush=True)
        return 1

    if not message and not events:
        if os.getenv("PUBLISH_ALERT_MODE")=="prepare":
            return _prepare_durable([],posts,events,state,run_id,telegram_on=telegram_on,ntfy_on=ntfy_on,base_failures=0,category=category)
        print('{"status":"no_posts_or_errors","messages_sent":0}', flush=True)
        return 0

    messages = [post_message(row, run_id) for row in posts]
    # An already-known held intent is not another failed API request. Keep
    # its daily audit trail, but reserve urgent phone alerts for NEW failures.
    known_holds_only = (bool(events) and category != "alert"
        and all(row.get("stage") == "previous_intent_hold"
                and row.get("reason") == "unreconciled_previous_intent"
                for row in events))
    if category == "alert" or events:
        # One actionable warning per run; every sanitized event stays intact
        # in the error-journal and 90-day artifact, even if the alert is short.
        details = []
        for entry in events[:8]:
            part = (f"• {entry.get('route') or '?'} / {entry.get('platform') or '?'}"
                    f" / {entry.get('video') or '-'}"
                    f" — {entry.get('stage')}: {entry.get('reason')}")
            if "http_status" in entry:
                part += f" (HTTP {entry['http_status']})"
            if "graph_code" in entry:
                part += f" [Graph {entry['graph_code']}]"
            details.append(part)
        if len(events) > 8:
            details.append(f"• Diğer {len(events) - 8} olayın tamamı GitHub error journal'da.")
        title = "ℹ️ Mevcut Instagram engelleri" if known_holds_only else "⚠️ Kısmi yayın sonucu" if posts else "🚨 Meta yayın uyarısı"
        warning = (message if category == "alert" else
                   (f"ℹ️ Daha önce bildirilen engeller devam ediyor; yeni Meta POST hatası yok.\nGitHub çalışma: {run_id}"
                    if known_holds_only else
                    f"🚨 Yayın iş akışında engel veya hata kaydedildi.\nGitHub çalışma: {run_id}"))
        warning += ("\n🧩 Kaydedilen hata/engel: " + str(len(events)) +
                    "\n" + "\n".join(details)) if events else ""
        messages.append((title, warning))
    run_url = f"https://github.com/emirhankaya985-cloud/auto-video-publisher/actions/runs/{run_id}"
    acknowledged = {"telegram": 0, "ntfy": 0}
    failures = 0
    if require_both:
        # Publishing remains committed; missing phone channels are separately
        # recorded as a DELIVERY failure, never a reason to repeat Meta POST.
        missing = []
        if not telegram_on:
            missing.append("Telegram")
            failures += 1
            record_error("telegram_notification", "notification_delivery_failed",
                         error=RuntimeError("Telegram configuration missing"))
        if not ntfy_on:
            missing.append("ntfy")
            failures += 1
            record_error("ntfy_notification", "notification_delivery_failed",
                         error=RuntimeError("ntfy configuration missing"))
        if missing and (telegram_on or ntfy_on):
            messages.append(("🚨 Bildirim kanalı eksik",
                             "Gönderi yeniden yayımlanmayacak. Eksik kanal: "
                             + ", ".join(missing)
                             + "\n🔎 " + run_url))
    if os.getenv("PUBLISH_ALERT_MODE")=="prepare":
        return _prepare_durable(messages,posts,events,state,run_id,telegram_on=telegram_on,
            ntfy_on=ntfy_on,base_failures=failures,category=category)
    for title, body in messages:
        if telegram_on:
            try:
                result = send_telegram(title, body)
                if result["server_ack"] is not True:
                    raise RuntimeError("telegram acknowledgment missing")
                acknowledged["telegram"] += 1
            except Exception as exc:
                failures += 1
                # Do not log credential-bearing provider error text.
                record_error("telegram_notification", "notification_delivery_failed",
                             error=exc)
                print(json.dumps({"status": "telegram_notification_failed",
                                  "error_type": type(exc).__name__}), flush=True)
        if ntfy_on:
            try:
                result = send_ntfy(
                    title, body,
                    priority=4 if title.startswith("🚨") else 2 if title.startswith("ℹ️") else 3,
                    tags=["warning"] if title.startswith("🚨") else
                         ["information_source"] if title.startswith("ℹ️") else ["white_check_mark"],
                    click=run_url, timeout=20, require_ack=True,
                )
                if result["server_ack"] is not True:
                    raise RuntimeError("ntfy acknowledgment missing")
                acknowledged["ntfy"] += 1
            except Exception as exc:
                failures += 1
                record_error("ntfy_notification", "notification_delivery_failed",
                             error=exc)
                print(json.dumps({"status": "ntfy_notification_failed",
                                  "error_type": type(exc).__name__}), flush=True)
    print(json.dumps({
        "status": "completed" if not failures else "partial_notification_failure",
        "confirmed_posts": len(posts),
        "alert": category == "alert" or bool(events),
        "recorded_errors": len(events),
        "telegram_server_acks": acknowledged["telegram"],
        "ntfy_server_acks": acknowledged["ntfy"],
        "delivery_failures": failures,
        "phone_delivery_verified": False,
    }, ensure_ascii=False), flush=True)
    return 1 if failures else 0

if __name__ == "__main__":
    sys.exit(main())
