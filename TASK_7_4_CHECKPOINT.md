# Task 7.4 checkpoint

Date: 2026-11-26 (Europe/Istanbul)

## Scope and current code

- Repository: `emirhankaya985-cloud/auto-video-publisher`; working branch: `feat/task74-engagement-health`.
- Base `main` at start: `1e63e0417c35eb04bdd598316245d6b2f4634285`.
- Preserved the 7.3 read-only engagement controls and the six active accounts: Tarladaki Fasulye, Gönle Düşen, Beyinsiz Penguen, Daily Laugh Lab, Film Mağarası, ToonZone. Film Second is not added; old history is untouched.
- Added a redacted engagement health report sourced only from existing completed main-branch isolated audit artifacts. It does not call Meta or create interactions. Missing history remains “unknown”; platform API acknowledgements are clearly marked as not platform-side proof.
- The daily report includes Facebook/Instagram route status, permission status, history, errors, blocked operations, last audit time and intervention. Instagram like writes are reported unsupported; Facebook automated likes remain disabled by policy.
- Daily ntfy and Telegram delivery use separate daily dedupe keys in the existing notification ledger. No live message was sent during development. Telegram inbox polling is explicitly off in this report workflow.
- Added a redacted JSON artifact with 90-day retention. No video schedule, publisher route, or publication history was changed.

## Verification evidence

- Current GitHub identity: `emirhankaya985-cloud` (active). No AFK identity was used.
- Latest isolated health run before this branch: #45718418035 (`workflow_dispatch`) and #45718400844 (`push`), both on `0a1b0ce56cff4aa904a27e57f1dca2dab7c9c7e7`; both evaluated the six-account read-only audit. They are not natural schedule evidence and are older than current main.
- Latest natural 15-minute isolated run observed: #45696797572, event `schedule`, SHA `aa4029036b25592721a10b1918d83762689e205b` (stale). No schedule run exists on current main SHA `1e63e0417c35eb04bdd598316245d6b2f4634285`. No workflow was manually dispatched for this check.
- Latest scheduled daily stats run observed: #45542901186 on `9e13baa19a81d1030fc03c2aa4a6affc545f1212` (stale); current SHA not yet naturally sampled.
- Secret names for `DASHBOARD_DATABASE_URL`, Telegram, and ntfy are configured in repository settings; their values were not read or printed. A prior publication sync run #45713566865 succeeded on stale SHA `aa4029036b25592721a10b1918d83762689e205b`.
- Neon discovery did not expose the production project in the connected Neon tool. Existing schema evidence covers publication receipts and `notification_events` dedupe, not engagement-health rows. No Neon health query/write or fabricated receipt was made. Health snapshots are retained as GitHub artifacts; dedupe may use the existing notification table when the secret connection works.

## Tests

- Focused: `python -m unittest test_engagement_health_report.py test_stats_reporter.py` — 16 passed.
- Full repository suite: `python -m unittest discover` — 1,511 passed, 16 skipped; exit 0.
- `daily_stats.yml` parsed with PyYAML; `git diff --check` passed.
- Notification tests use mocks; no real Telegram/ntfy message, Meta interaction, or production database write was performed.

## Pending before completion

- PR and CI status: not created/observed yet.
- A future natural schedule on merged/current main is needed to verify the new workflow code runs in GitHub Actions. This checkpoint does not claim that evidence.
- Per-account historical verified interaction counts cannot be recovered from aggregate legacy API-ACK rows; report says unknown rather than zero.
- Neon health persistence needs the owner to expose/confirm an authorized existing Neon project and approve a compatible health-record schema. Do not write this into `publication_events`.
- Actual Telegram/ntfy delivery is not proven until a normal daily scheduled run receives provider acknowledgements; no test message was sent.

## Cost and unrelated deletion request

- Additional service cost: 0 TL; no service was created.
- The separate proposal to automatically delete videos after 48 hours when views are below 10 was not implemented, tested live, or enabled. No videos were deleted. It needs its own explicit safeguards and task scope.
