# Owner requested status-only Telegram report

The owner narrowed Telegram management to `/durum` (also plain `durum`).
`/stok`, `/durdur`, and `/devam` are not exposed by the worker. Existing status
code may read settings/history and send the timetable; it cannot mutate the
publisher through these commands. Subtitles remain unchanged and off.

This marker authorizes one delivery of the actual settings/ledger timetable to
the existing, previously verified Telegram report chat. No social-media upload,
webhook replacement, secret change or paid host is involved.
The workflow archives its prepared HTML before sending once. Server ACK is
separate from Android display. A rerun is skipped rather than blindly repeating
an uncertain send. Never touch this marker to test publishing.

The status-only inbox reuses the existing owner-authenticated handler in bounded
GitHub Actions batches, nominally every five minutes (schedule delays possible).
There is no always-on server or AI request. A single concurrency group prevents
overlapping batches; an active webhook or 409 consumer conflict blocks polling.
Those conflicts are latched in the archived checkpoint; later scheduled batches
make no Telegram polling requests until an operator reviews the ownership issue.
Do not also run the old long-polling worker with this bot. Offset SQLite is
archived BEFORE replies; reruns never repeat a possibly delivered message.
Checkpoint retention is seven days to bound storage. Expired/malformed state
blocks rather than resetting the offset. Private chat ID binds the human owner;
a group requires the existing explicit owner ID. Stop only the inbox using
TELEGRAM_STATUS_INBOX_ENABLED=false; the social publisher is unaffected.
