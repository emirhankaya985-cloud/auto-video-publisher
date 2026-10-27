# Telegram + ntfy notification setup (985)

The 985 public automation keeps ntfy and adds optional Telegram delivery for:
- Video publication success, failure, and recovery
- Daily 23:15 TRT per-account views and accessible video totals
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

A daily Meta-only report runs unless `vars.META_REPORTING_ENABLED == 'false'`.
The legacy `AUTOMATION_ENABLED` flag is unrelated and must stay off.
Publication routes have their separate rights/enablement guards.
Do not enable any route just to test notifications.

## Detailed Telegram comparisons

Daily reports now send three bounded HTML messages: the six-account daily
table, the exact seven-day comparison, and growth leaders/platform breakdown.
The first table shows yesterday's cumulative video total, current total,
absolute increase and percentage increase. The weekly table uses the snapshot
dated exactly seven calendar days earlier; a different date is never substituted.
Additional fields include top three absolute-growth accounts, each account's
share of the known system total, platform counters and covered video records.

Percent = `(current cumulative total - baseline cumulative total) / baseline * 100`.
It is not a comparison of today's view velocity against yesterday's daily views.
Missing history, changed video coverage, counter corrections and zero baselines
do not yield invented percentages. A seven-day baseline must actually exist;
the first archived date is shown in the weekly message. Measurements carry their
actual timestamp; an intraday manual report is not a completed calendar day.

HTML labels are escaped, each table is kept within the message budget, and
accepted message parts are never automatically retried. The JSON comparison
evidence is retained as `account-views-comparison` for 90 days in the report run.
ntfy keeps the existing compact digest. Only Telegram receives the three-part
detailed tables. Each server receipt is checked; phone UI delivery is separate.
