# Meta-only verification activation — 25 October 2026

This one-time marker requests exactly two safe `main` push jobs after review:

1. `Hesap Bazli Izlenme Raporu`: read-only Meta analytics and Telegram/ntfy notification, no YouTube or Drive writes.
2. `Read-only Meta connection audit`: verify saved FB page and connected IG identity and permissions, no publishing calls.

Normal nightly analytics at 23:59 TRT and independent next-morning watcher at 07:10 TRT stay active by default. Set the repository variable `META_REPORTING_ENABLED=false` to disable only these two reporting jobs (not the Meta video publisher).

No state/claim reset, no Meta upload POST, no secret/token mutation, no legacy `AUTOMATION_ENABLED`, and no change to source media or ToonZone cover requirements.
