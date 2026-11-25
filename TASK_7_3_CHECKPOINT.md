# Task 7.3 checkpoint

Date: 2026-11-26 (Europe/Istanbul)

## Delivered

- Repository: `emirhankaya985-cloud/auto-video-publisher`; merged PR [#325](https://github.com/emirhankaya985-cloud/auto-video-publisher/pull/325).
- Production `main`: `0a1b0ce56cff4aa904a27e57f1dca2dab7c9c7e7`.
- Existing `fix/engagement-readonly-health-20261126` fixes were preserved: Film Second excluded from active engagement identities and isolated health reports treat missing/invalid evidence as unknown. Shared publisher allowlist/history was left intact.
- Engagement schedule remains every 15 minutes. Main and isolated workflows are read-only; manual `apply`, intent uploads, and engagement POST execution are disabled. Direct unsupported calls fail closed.
- No Meta interaction, Telegram/NTFY message, or database write was sent.

## Read-only live evidence

- Isolated health run **45718400844** (push after merge) and manual read-only run **45718418035** both completed successfully on the merged SHA. Each evaluated all six accounts independently. The manual run is not evidence of a natural schedule trigger.
- The run's account inventory contains all six requested accounts with **6 Facebook and 6 Instagram identities**, and no unverified account/platform routes. Facebook `pages_manage_engagement` permission checks passed for all six accounts. Instagram identity/token discovery succeeded, but Instagram like writes are unsupported and not enabled.
- Accounts in the verified inventory: Tarladaki Fasulye, Gönle Düşen, Beyinsiz Penguen, Daily Laugh Lab, Film Mağarası, ToonZone. Film Second is absent.
- New engagement actions: **0**. The workflow produced no engagement plans. The historical ledger contains 174 Facebook and 0 Instagram API-ACK rows in the restored view; these are historical API acknowledgements only, not platform-side verification. Historical Instagram acknowledgements remain preserved in prior artifacts.
- The most recent natural engagement run found before the change was **45639089352**, on stale SHA `aa4029036b25592721a10b1918d83762689e205b`. No natural schedule run on the merged SHA has yet been observed.

## API and policy

- Meta's Instagram Media API exposes engagement counts as readable fields; no supported Instagram like-creation operation is documented. Instagram writes are classified `unsupported_by_verified_api`.
- Facebook Page-post likes have a supported API under narrow Page/token/task/permission conditions. Automated cross-account likes are nevertheless disabled as coordinated metric inflation; they are classified `disabled_by_policy`.
- The 15-minute schedule remains a health audit only. Meta rate limits and restriction responses are respected; no retries or alternate-actor bypasses are used.

## Tests

- Focused engagement suite: `python -m unittest test_meta_cross_engagement.py test_meta_cross_engagement_receipts.py` — passed (81 tests; 16 legacy live-write expectations skipped).
- Full suite: `python -m unittest discover` — exit 0, 1,476 tests.
- Workflow YAML parsed with PyYAML; `git diff --check` passed.
- PR #325 checks passed: engagement tests and repository regression; the engagement write job was skipped on the PR.

## Remaining blockers

- Engagement health/receipt data is not connected to Neon. The existing Neon sync covers publication receipts only, and connected Neon discovery did not expose the requested production project. No Neon engagement rows were read or written.
- A daily Turkish health report through Telegram and NTFY is not implemented. Existing engagement receipts were Telegram-only; they are no longer sent by the read-only workflow. No delivery is claimed.
- Account-level daily reporting of last run, errors, blocked operations, and token/permission state is not persisted. The successful diagnostic run proves identity and permission reads at that run time, not ongoing token health.
- Natural schedule after merge remains unverified. The workflow cron and previous schedule records were inspected, but the new SHA has only push and manual run evidence so far.

## Official references

- [Meta Instagram Media reference](https://developers.facebook.com/docs/instagram-platform/reference/instagram-media/v21.0/)
- [Meta Page Post Likes reference](https://developers.facebook.com/docs/graph-api/reference/page-post/likes/)
- [Meta Graph API rate limits](https://developers.facebook.com/docs/graph-api/overview/rate-limiting/)
