# Meta-only verification activation — 25 October 2026

This one-time marker requests exactly two safe `main` push jobs after review:

1. `Hesap Bazli Izlenme Raporu`: read-only Meta analytics and Telegram/ntfy notification, no YouTube or Drive writes.
2. `Read-only Meta connection audit`: verify saved FB page and connected IG identity and permissions, no publishing calls.

Normal nightly analytics at 23:15 TRT and independent next-morning watcher at 07:10 TRT stay active by default. Set the repository variable `META_REPORTING_ENABLED=false` to disable only these two reporting jobs (not the Meta video publisher).

No state/claim reset, no Meta upload POST, no secret/token mutation, no legacy `AUTOMATION_ENABLED`, and no change to source media or ToonZone cover requirements.

## Owner-requested manual verification — 27 October 2026

The owner explicitly requested an immediate manual test of the account daily/lifetime views report after PR #25. Updating this existing marker reruns the two documented read-only workflows above, including the report to the configured Telegram/ntfy channels. This push is a manual verification request, not a scheduled nightly run. It does not authorize or trigger video publishing, state/claim deletion, credential changes, or activation of legacy publishing. The current 23:15 TRT nightly schedule is preserved.

## Detailed Telegram report verification — 27 October 2026

After PR #26, the owner explicitly requested the daily/weekly percentage tables and additional account performance detail on Telegram. This marker requests one live report with the three bounded Telegram HTML parts, current counters and existing archived baselines. Check all three Telegram server receipts and the comparison JSON artifact. Missing seven-day history remains unavailable; no dates or percentages are fabricated. Existing read-only account audit is unchanged; no video publishing or credential changes are requested.
