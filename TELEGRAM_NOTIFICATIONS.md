# Telegram + ntfy notification setup (985)

The 985 public automation keeps ntfy and adds optional Telegram delivery for:
- Video publication success, failure, and recovery
- Daily 23:59 TRT per-account views and lifetime totals
- Failed daily report and next-morning missed-report watchdog

In repository **Settings → Secrets and variables → Actions → Repository secrets** configure:
- `TELEGRAM_BOT_TOKEN` — BotFather token, stored only as a secret
- `TELEGRAM_CHAT_ID` — numeric ID of the chat that opened the bot with /start

Existing `NTFY_TOPIC_URL` / `NTFY_TOPIC` values are unchanged.
The public repository contains no token, chat ID, ntfy topic, or customer data.

To test after secrets are set, run the manually triggered
**Telegram connection smoke** workflow in GitHub Actions. It sends a clearly
marked test message and never publishes a video. An HTTP/Telegram server
ACK is *not* phone push delivery proof.

A daily report still runs only if `vars.AUTOMATION_ENABLED == 'true'`,
and publication routes have their separate rights/enablement guards.
Do not enable any route just to test notifications.
